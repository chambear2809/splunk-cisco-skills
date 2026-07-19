#!/usr/bin/env python3
"""Offline behavior tests for the Cisco collaboration render-first router."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/cisco-collaboration-setup"
RENDERER_PATH = SKILL_DIR / "scripts/render_assets.py"
SETUP_PATH = SKILL_DIR / "scripts/setup.sh"
VALIDATE_PATH = SKILL_DIR / "scripts/validate.sh"
TEMPLATE_PATH = SKILL_DIR / "template.example"
LEDGER_PATH = SKILL_DIR / "references/source-ledger.json"


def load_renderer():
    spec = importlib.util.spec_from_file_location("cisco_collaboration_render_assets", RENDERER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


RENDERER = load_renderer()


@contextmanager
def private_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=".cisco-collaboration-test-", dir=REPO_ROOT) as raw:
        root = Path(raw)
        root.chmod(0o700)
        yield root


def run_command(*argv: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        list(argv),
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def base_spec() -> dict[str, Any]:
    return copy.deepcopy(
        RENDERER.strict_load_yaml_or_json(
            TEMPLATE_PATH.read_text(encoding="utf-8"),
            source=str(TEMPLATE_PATH),
        )
    )


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def write_spec(root: Path, spec: dict[str, Any], name: str = "spec.json") -> Path:
    path = root / name
    write_json(path, spec)
    return path


def load_validated_spec(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = write_spec(root, spec)
    validated, _path, _digest = RENDERER.load_spec(path)
    return validated


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_bundle(root: Path, spec: dict[str, Any] | None = None, *, validate: bool = False) -> tuple[Path, dict[str, Any]]:
    spec_path = write_spec(root, spec or base_spec())
    out = root / "bundle"
    argv = [
        "bash",
        str(SETUP_PATH),
        "--spec",
        str(spec_path),
        "--output-dir",
        str(out),
        "--json",
    ]
    if validate:
        argv.append("--validate")
    result = run_command(*argv)
    assert result.returncode == 0, result.stdout + result.stderr
    return out, json.loads(result.stdout)


def set_flat_file_evidence(
    spec: dict[str, Any],
    root: Path,
    family: str,
    *,
    cmr_variant: str = "current_example",
) -> Path:
    if family == "cdr":
        fields = [
            "cdrRecordType",
            "globalCallID_callManagerId",
            "globalCallID_callId",
            "origLegCallIdentifier",
            "dateTimeOrigination",
            "callingPartyNumber",
            "finalCalledPartyNumber",
        ]
        types = ["INTEGER", "INTEGER", "INTEGER", "INTEGER", "INTEGER", "VARCHAR(50)", "VARCHAR(50)"]
        values = ["1", "7", "9001", "10001", "1784462400", "masked-calling", "masked-called"]
        filename = "cdr_cluster_node_20260719_120000_000001.csv"
    else:
        call_field, directory_field = (
            ("globalCallId_callId", "directoryNumber")
            if cmr_variant == "field_table"
            else ("globalCallID_callId", "directoryNum")
        )
        fields = [
            "cdrRecordType",
            "globalCallID_callManagerId",
            call_field,
            "nodeId",
            directory_field,
            "callIdentifier",
            "dateTimeStamp",
            "numberPacketsLost",
            "jitter",
            "latency",
        ]
        directory_type = "INTEGER" if cmr_variant == "field_table" else "VARCHAR(50)"
        directory_value = "20001" if cmr_variant == "field_table" else "masked-directory"
        types = ["INTEGER", "INTEGER", "INTEGER", "INTEGER", directory_type, "INTEGER", "INTEGER", "INTEGER", "INTEGER", "INTEGER"]
        values = ["2", "7", "9001", "2", directory_value, "10001", "1784462400", "0", "3", "8"]
        filename = f"cmr_cluster_node_20260719_120000_{'000001' if cmr_variant == 'field_table' else '000002'}.csv"
    sample = root / filename
    sample.write_text(
        ",".join(fields) + "\n" + ",".join(types) + "\n" + ",".join(values) + "\n",
        encoding="utf-8",
    )
    sample.chmod(0o600)
    route = spec["products"]["cucm"][family]
    route["enabled"] = True
    route["index"] = f"cucm_{family}"
    route["sourcetype"] = f"cisco:cucm:{family}"
    route["evidence"] = {
        "file_type": family,
        "header_rows": 2,
        "sample_path": sample.name,
        "sha256": sha256(sample),
        "record_count": 1,
        "observed_fields": fields,
        "export_path": f"/srv/cucm/{family}",
        "receiver_owner": "collaboration-operations",
        "collection_evidence": f"Reviewed independent {family.upper()} SFTP receiver ownership.",
        "source_type_origin": "customer_normalized",
    }
    return sample


def update_manifest_hash(out: Path, relative: str) -> None:
    manifest_path = out / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][relative] = sha256(out / relative)
    write_json(manifest_path, manifest)


def update_marker_commitments(out: Path, *relatives: str) -> None:
    marker_path = out / RENDERER.MARKER_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    for relative in relatives:
        marker["artifact_commitments"][relative] = sha256(out / relative)
    marker["artifact_commitments"]["artifact-manifest.json"] = sha256(
        out / "artifact-manifest.json"
    )
    write_json(marker_path, marker)


def coherent_rehash(out: Path, *relatives: str) -> None:
    for relative in relatives:
        update_manifest_hash(out, relative)
    update_marker_commitments(out, *relatives)


def validate_output(
    out: Path,
    *,
    spec: Path | None = None,
    expected_spec_sha256: str | None = None,
) -> subprocess.CompletedProcess[str]:
    argv = ["bash", str(VALIDATE_PATH), "--output-dir", str(out), "--json"]
    if spec is not None:
        argv.extend(["--spec", str(spec)])
    if expected_spec_sha256 is not None:
        argv.extend(["--expected-spec-sha256", expected_spec_sha256])
    return run_command(*argv)


def test_documented_default_preview_is_strict_json_and_zero_write() -> None:
    default_output = REPO_ROOT / "cisco-collaboration-rendered"
    assert not default_output.exists()
    result = run_command(
        "bash",
        str(SETUP_PATH),
        "--spec",
        str(TEMPLATE_PATH),
        "--dry-run",
        "--json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "preview"
    assert payload["writes"] == 0
    assert payload["live_service_calls"] == 0
    assert not default_output.exists()


def test_real_render_validate_private_modes_and_single_json_output() -> None:
    with private_workspace() as root:
        out, payload = render_bundle(root, validate=True)
        assert payload["status"] == "rendered"
        assert payload["validation_status"] == "offline_structure_and_provenance_checked"
        assert payload["provenance_status"] == "verified_against_trusted_spec_and_local_evidence"
        assert stat.S_IMODE(out.stat().st_mode) == 0o700
        for path in out.rglob("*"):
            assert not path.is_symlink()
            expected = 0o700 if path.is_dir() else 0o600
            assert stat.S_IMODE(path.stat().st_mode) == expected
        validated = validate_output(out)
        assert validated.returncode == 0, validated.stdout + validated.stderr
        assert json.loads(validated.stdout)["status"] == "offline_structure_checked"


def test_setup_validate_external_spec_digest_matches_or_fails_before_write() -> None:
    with private_workspace() as root:
        spec_path = write_spec(root, base_spec())
        out = root / "bundle"
        accepted = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--validate",
            "--expected-spec-sha256",
            sha256(spec_path),
            "--json",
        )
        assert accepted.returncode == 0, accepted.stdout + accepted.stderr
        payload = json.loads(accepted.stdout)
        assert payload["status"] == "rendered"
        assert payload["validation_status"] == "offline_structure_and_provenance_checked"

        wrong_out = root / "wrong-bundle"
        rejected = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(wrong_out),
            "--validate",
            "--expected-spec-sha256",
            "0" * 64,
            "--json",
        )
        assert rejected.returncode == 2
        assert not wrong_out.exists()


@pytest.mark.parametrize("force_fallback", [False, True])
def test_strict_loader_rejects_duplicate_alias_flow_and_escaped_key_bypasses(force_fallback: bool) -> None:
    canaries = [
        "a: {status: UNKNOWN, status: completed}\n",
        '"sta\\u0074us": UNKNOWN\n',
        "a: &loop [*loop]\n",
        "a:\n  enabled: false\n  enabled: true\n",
        "items:\n  - status: UNKNOWN\n    status: completed\n",
        "a: [one, two]\n",
        "a: !!str value\n",
        "defaults: &base\n  status: UNKNOWN\na:\n  <<: *base\n",
    ]
    for text in canaries:
        with pytest.raises((RENDERER.SpecError, ValueError)):
            RENDERER.strict_load_yaml_or_json(
                text,
                source="canary.yaml",
                force_fallback=force_fallback,
            )
    assert RENDERER.strict_load_yaml_or_json(
        "items: []\n",
        source="empty-list.yaml",
        force_fallback=force_fallback,
    ) == {"items": []}


def test_strict_json_duplicate_decoded_key_is_rejected() -> None:
    with pytest.raises(RENDERER.SpecError, match="duplicate JSON key"):
        RENDERER.strict_load_yaml_or_json(
            '{"a": {"status": "UNKNOWN", "status": "completed"}}',
            source="duplicate.json",
        )


def test_full_template_and_scalar_edges_are_equivalent_under_pyyaml_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("yaml")
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    pyyaml_tree = RENDERER.strict_load_yaml_or_json(
        template_text,
        source=str(TEMPLATE_PATH),
        force_fallback=False,
    )
    fallback_tree = RENDERER.strict_load_yaml_or_json(
        template_text,
        source=str(TEMPLATE_PATH),
        force_fallback=True,
    )
    assert RENDERER.canonical_json(pyyaml_tree) == RENDERER.canonical_json(fallback_tree)

    scalar_edges = """root:
  empty: []
  enabled: true
  disabled: false
  positive: 17
  zero: 0
  negative: -3
  decimal: 10.5
  plain: alpha-beta
  single: 'alpha beta'
  double: "alpha beta"
  items:
    -
      name: first
      disposition: handoff_only
"""
    pyyaml_edges = RENDERER.strict_load_yaml_or_json(
        scalar_edges,
        source="scalar-edges.yaml",
        force_fallback=False,
    )
    fallback_edges = RENDERER.strict_load_yaml_or_json(
        scalar_edges,
        source="scalar-edges.yaml",
        force_fallback=True,
    )
    assert RENDERER.canonical_json(pyyaml_edges) == RENDERER.canonical_json(fallback_edges)

    with private_workspace() as root:
        args = SimpleNamespace(
            spec=str(TEMPLATE_PATH),
            output_dir=str(root / "bundle"),
            dry_run=True,
            validate_only=False,
            replace_existing=False,
            json=True,
        )
        pyyaml_preview = RENDERER.render(args)
        real_loader = RENDERER.strict_load_yaml_or_json

        def forced_fallback(text: str, *, source: str, force_fallback: bool = False):
            return real_loader(text, source=source, force_fallback=True)

        monkeypatch.setattr(RENDERER, "strict_load_yaml_or_json", forced_fallback)
        fallback_preview = RENDERER.render(args)
        assert fallback_preview == pyyaml_preview
        assert fallback_preview["writes"] == 0
        assert not (root / "bundle").exists()


def test_realistic_cdr_and_current_exported_cmr_validate() -> None:
    with private_workspace() as root:
        spec = base_spec()
        set_flat_file_evidence(spec, root, "cdr")
        set_flat_file_evidence(spec, root, "cmr", cmr_variant="current_example")
        validated = load_validated_spec(root, spec)
        readiness = RENDERER.build_readiness(validated)
        by_path = {row["path"]: row for row in readiness["routes"]}
        assert by_path["cucm.cdr"]["status"] == "locally_evidence_qualified"
        assert by_path["cucm.cmr"]["status"] == "locally_evidence_qualified"
        assert by_path["cucm.cdr"]["local_sample_validated"] is True
        assert by_path["cucm.cmr"]["local_sample_validated"] is True


def test_cmr_field_description_compatibility_variant_cannot_qualify() -> None:
    with private_workspace() as root:
        spec = base_spec()
        set_flat_file_evidence(spec, root, "cmr", cmr_variant="field_table")
        with pytest.raises(RENDERER.SpecError, match="field-description compatibility"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize(
    ("family", "variant", "field"),
    [
        ("cdr", "current_example", "callingPartyNumber"),
        ("cdr", "current_example", "finalCalledPartyNumber"),
        ("cmr", "current_example", "directoryNum"),
        ("cmr", "field_table", "directoryNumber"),
    ],
)
def test_required_export_signature_fields_reject_wrong_type_tokens(
    family: str,
    variant: str,
    field: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family, cmr_variant=variant)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        rows[1][rows[0].index(field)] = "BANANA"
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        spec["products"]["cucm"][family]["evidence"]["sha256"] = sha256(sample)
        with pytest.raises(RENDERER.SpecError, match="incorrect required signature field type"):
            load_validated_spec(root, spec)


def test_cdr_cmr_reject_minimal_fake_wrong_case_type_row_width_record_type_and_reuse() -> None:
    with private_workspace() as root:
        mutation_names = (
            "minimal",
            "wrong_case",
            "empty_type",
            "width",
            "record_type",
            "two_rows",
        )
        for mutation in mutation_names:
            spec = base_spec()
            sample = set_flat_file_evidence(spec, root, "cdr")
            rows = sample.read_text(encoding="utf-8").splitlines()
            if mutation == "minimal":
                rows = ["cdrRecordType", "INTEGER", "1"]
                spec["products"]["cucm"]["cdr"]["evidence"]["observed_fields"] = ["cdrRecordType"]
            elif mutation == "wrong_case":
                rows = [row.replace("globalCallID_callManagerId", "globalCallId_callManagerId") for row in rows]
                spec["products"]["cucm"]["cdr"]["evidence"]["observed_fields"] = rows[0].split(",")
            elif mutation == "empty_type":
                type_cells = rows[1].split(",")
                type_cells[1] = ""
                rows[1] = ",".join(type_cells)
            elif mutation == "width":
                rows[2] = ",".join(rows[2].split(",")[:-1])
            elif mutation == "record_type":
                cells = rows[2].split(",")
                cells[0] = "2"
                rows[2] = ",".join(cells)
            elif mutation == "two_rows":
                rows = rows[:2]
                spec["products"]["cucm"]["cdr"]["evidence"]["record_count"] = 0
            sample.write_text("\n".join(rows) + "\n", encoding="utf-8")
            spec["products"]["cucm"]["cdr"]["evidence"]["sha256"] = sha256(sample)
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, spec)

        spec = base_spec()
        cdr = set_flat_file_evidence(spec, root, "cdr")
        set_flat_file_evidence(spec, root, "cmr")
        spec["products"]["cucm"]["cmr"]["evidence"]["sample_path"] = cdr.name
        spec["products"]["cucm"]["cmr"]["evidence"]["sha256"] = sha256(cdr)
        with pytest.raises(RENDERER.SpecError):
            load_validated_spec(root, spec)


def test_cmr_rejects_mixed_or_unknown_alias_and_wrong_manager_case() -> None:
    with private_workspace() as root:
        for old, new in (
            ("directoryNum", "directoryNumber"),
            ("directoryNum", "directoryNo"),
            ("globalCallID_callManagerId", "globalCallId_callManagerId"),
        ):
            spec = base_spec()
            sample = set_flat_file_evidence(spec, root, "cmr", cmr_variant="current_example")
            rows = [row.replace(old, new) for row in sample.read_text(encoding="utf-8").splitlines()]
            sample.write_text("\n".join(rows) + "\n", encoding="utf-8")
            evidence = spec["products"]["cucm"]["cmr"]["evidence"]
            evidence["sha256"] = sha256(sample)
            evidence["observed_fields"] = rows[0].split(",")
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, spec)


@pytest.mark.parametrize("family", ["cdr", "cmr"])
@pytest.mark.parametrize("invalid_value", ["", "not-a-number"])
def test_cdr_cmr_reject_blank_or_nonnumeric_required_integer_cells(
    family: str,
    invalid_value: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        manager_index = rows[0].index("globalCallID_callManagerId")
        rows[2][manager_index] = invalid_value
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        spec["products"]["cucm"][family]["evidence"]["sha256"] = sha256(sample)
        with pytest.raises(RENDERER.SpecError, match="ASCII base-10 integer"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize("family", ["cdr", "cmr"])
@pytest.mark.parametrize("invalid_value", [" 7", "7 ", "\t7", "7\t"])
def test_cdr_cmr_reject_integer_cell_surrounding_whitespace(
    family: str,
    invalid_value: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        manager_index = rows[0].index("globalCallID_callManagerId")
        rows[2][manager_index] = invalid_value
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        spec["products"]["cucm"][family]["evidence"]["sha256"] = sha256(sample)
        with pytest.raises(RENDERER.SpecError, match="ASCII base-10 integer"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize("family", ["cdr", "cmr"])
def test_cdr_cmr_huge_ascii_integer_is_checked_lexically_without_traceback(family: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        manager_index = rows[0].index("globalCallID_callManagerId")
        rows[2][manager_index] = "9" * 5000
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        spec["products"]["cucm"][family]["evidence"]["sha256"] = sha256(sample)
        validated = load_validated_spec(root, spec)
        assert validated["products"]["cucm"][family]["enabled"] is True


@pytest.mark.parametrize(
    ("family", "field", "value", "accepted"),
    [
        ("cdr", "globalCallID_callManagerId", "0", False),
        ("cdr", "globalCallID_callManagerId", "-1", False),
        ("cdr", "globalCallID_callManagerId", "+1", True),
        ("cmr", "globalCallID_callId", "0", False),
        ("cmr", "globalCallID_callId", "-1", False),
        ("cmr", "globalCallID_callId", "+1", True),
        ("cmr", "jitter", "-1", False),
        ("cmr", "jitter", "0", True),
        ("cmr", "jitter", "+1", True),
        ("cmr", "numberPacketsLost", "-1", True),
        ("cmr", "dateTimeStamp", "-1", True),
        ("cmr", "latency", "-1", True),
        ("cdr", "dateTimeOrigination", "-1", True),
    ],
)
def test_cisco_integer_sign_semantics(
    family: str,
    field: str,
    value: str,
    accepted: bool,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        rows[2][rows[0].index(field)] = value
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        spec["products"]["cucm"][family]["evidence"]["sha256"] = sha256(sample)
        if accepted:
            assert load_validated_spec(root, spec)["products"]["cucm"][family]["enabled"] is True
        else:
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, spec)


@pytest.mark.parametrize("family", ["cdr", "cmr"])
@pytest.mark.parametrize("value", ["27", "", "not-a-number"])
def test_every_declared_integer_cell_is_validated_including_non_key_columns(
    family: str,
    value: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, family)
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        rows[0].append("customIntegerObservation")
        rows[1].append("INTEGER")
        rows[2].append(value)
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        evidence = spec["products"]["cucm"][family]["evidence"]
        evidence["observed_fields"] = rows[0]
        evidence["sha256"] = sha256(sample)
        if value == "27":
            assert load_validated_spec(root, spec)["products"]["cucm"][family]["enabled"] is True
        else:
            with pytest.raises(RENDERER.SpecError, match="ASCII base-10 integer"):
                load_validated_spec(root, spec)


@pytest.mark.parametrize("header", ["pii-customer777@example.com", "password"])
def test_cdr_cmr_header_dlp_rejects_email_and_secret_names(header: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        sample = set_flat_file_evidence(spec, root, "cdr")
        rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
        rows[0].append(header)
        rows[1].append("VARCHAR(50)")
        rows[2].append("redacted")
        sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
        evidence = spec["products"]["cucm"]["cdr"]["evidence"]
        evidence["observed_fields"] = rows[0]
        evidence["sha256"] = sha256(sample)
        with pytest.raises(RENDERER.SpecError):
            load_validated_spec(root, spec)


def test_spec_basename_is_not_persisted_and_credential_shaped_owner_fails_before_write() -> None:
    basename_literal = "pii-customer777@example.com"
    with private_workspace() as root:
        spec_path = write_spec(root, base_spec(), f"{basename_literal}.json")
        out = root / "bundle"
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--json",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        for artifact in out.rglob("*"):
            if artifact.is_file():
                assert basename_literal not in artifact.read_text(encoding="utf-8")
        metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["source_spec"]["name_persisted"] is False
        assert set(metadata["source_spec"]) == {"sha256", "name_persisted"}

        unsafe = base_spec()
        unsafe["project"]["owner"] = "AKIA1234567890ABCDEF"
        unsafe_path = write_spec(root, unsafe, "unsafe-owner.json")
        unsafe_out = root / "unsafe-owner-bundle"
        rejected = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(unsafe_path),
            "--output-dir",
            str(unsafe_out),
            "--json",
        )
        assert rejected.returncode == 2
        assert "credential-shaped" in rejected.stdout + rejected.stderr
        assert not unsafe_out.exists()


@pytest.mark.parametrize(
    "credential",
    [
        "sk-" + "A" * 24,
        "sk-proj-" + "B" * 24,
        "AIza" + "C" * 35,
    ],
)
@pytest.mark.parametrize(
    "copied_path",
    [
        "project.name",
        "project.environment",
        "project.owner",
        "privacy.restricted_role",
        "cms.classifier",
        "meeting_management.classifier",
        "cdr.header",
        "cmr.header",
    ],
)
def test_openai_and_google_shapes_fail_across_operator_controlled_persisted_text(
    credential: str,
    copied_path: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        if copied_path.startswith("project."):
            spec["project"][copied_path.rsplit(".", 1)[1]] = credential
        elif copied_path == "privacy.restricted_role":
            spec["privacy"]["restricted_role"] = credential
        elif copied_path == "cms.classifier":
            spec["products"]["cms"]["syslog"]["classifier"] = {
                "mode": "exact_host",
                "value": credential,
            }
            spec["products"]["meeting_management"]["classifier"] = {
                "mode": "exact_host",
                "value": "cmm.example.invalid",
            }
        elif copied_path == "meeting_management.classifier":
            spec["products"]["cms"]["syslog"]["classifier"] = {
                "mode": "exact_host",
                "value": "cms.example.invalid",
            }
            spec["products"]["meeting_management"]["classifier"] = {
                "mode": "exact_host",
                "value": credential,
            }
        else:
            family = copied_path.split(".", 1)[0]
            sample = set_flat_file_evidence(spec, root, family)
            rows = [row.split(",") for row in sample.read_text(encoding="utf-8").splitlines()]
            rows[0].append(credential)
            rows[1].append("VARCHAR(50)")
            rows[2].append("redacted")
            sample.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
            evidence = spec["products"]["cucm"][family]["evidence"]
            evidence["observed_fields"] = rows[0]
            evidence["sha256"] = sha256(sample)
        out = root / "bundle"
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(write_spec(root, spec)),
            "--output-dir",
            str(out),
            "--json",
        )
        assert result.returncode == 2
        assert not out.exists()


@pytest.mark.parametrize(
    "sensitive_component",
    [
        "alice@example.com",
        "sk-" + "A" * 24,
        "sk-proj-" + "B" * 24,
        "AIza" + "C" * 35,
        "AKIA1234567890ABCDEF",
        "ghp_" + "D" * 24,
        "xoxb-1234567890ABCDEF",
        "eyJabcdefgh.ijklmnopq.rstuvwxyz",
        "Bearer ABCDEFGHIJK",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_sensitive_resolved_output_and_derived_child_paths_fail_before_write(
    sensitive_component: str,
) -> None:
    with private_workspace() as root:
        out = root / sensitive_component
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(TEMPLATE_PATH),
            "--output-dir",
            str(out),
            "--dry-run",
            "--json",
        )
        assert result.returncode == 2
        assert not out.exists()


def test_uuid_like_operational_identifier_and_output_path_remain_allowed() -> None:
    uuid_value = "550e8400-e29b-41d4-a716-446655440000"
    with private_workspace() as root:
        spec = base_spec()
        spec["project"]["owner"] = uuid_value
        out = root / uuid_value
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(write_spec(root, spec)),
            "--output-dir",
            str(out),
            "--dry-run",
            "--json",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["writes"] == 0
        assert not out.exists()


def test_hardlinked_and_symlinked_evidence_fail_closed() -> None:
    with private_workspace() as root:
        spec = base_spec()
        original = set_flat_file_evidence(spec, root, "cdr")
        hardlink = root / "cdr_cluster_node_20260719_120000_hardlink.csv"
        os.link(original, hardlink)
        evidence = spec["products"]["cucm"]["cdr"]["evidence"]
        evidence["sample_path"] = hardlink.name
        evidence["sha256"] = sha256(hardlink)
        with pytest.raises(RENDERER.SpecError, match="single-link"):
            load_validated_spec(root, spec)

        spec = base_spec()
        target = set_flat_file_evidence(spec, root, "cdr")
        link = root / "cdr_cluster_node_20260719_120000_symlink.csv"
        link.symlink_to(target.name)
        evidence = spec["products"]["cucm"]["cdr"]["evidence"]
        evidence["sample_path"] = link.name
        evidence["sha256"] = sha256(target)
        with pytest.raises(RENDERER.SpecError, match="symlink"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize(
    ("transport", "port", "authentication", "trust"),
    [
        ("udp", 5514, "none", False),
        ("tcp", 12345, "none", False),
        ("tls", 6514, "unidirectional_x509", True),
    ],
)
def test_cucm_remote_audit_profiles_always_keep_blocking_listener_gap(
    transport: str,
    port: int,
    authentication: str,
    trust: bool,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        profile = spec["products"]["cucm"]["syslog"]
        profile.update(
            transport=transport,
            receiver_port=port,
            tls_authentication=authentication,
            trust_requirements_reviewed=trust,
        )
        validated = load_validated_spec(root, spec)
        gaps = {row["id"]: row for row in RENDERER.build_gaps(validated)["gaps"]}
        route = RENDERER.build_sc4s_plan(validated)["routes"][0]
        handoff = RENDERER.build_handoff_plan(validated, root / "bundle")
        argv = next(
            row["commands"][0]
            for row in handoff["sections"]
            if row["name"] == "collaboration-syslog"
        )
        assert route["device_scope"] == "remote_audit_logging"
        assert route["device_port"] == port
        assert route["port_origin"] == "operator_selected_not_cisco_default"
        assert route["listener_readiness"] == "unresolved_handoff_gap"
        assert gaps["cucm_sc4s_listener"]["blocking"] is True
        assert not any("cisco_ucm:" in argument for argument in argv)


def test_cucm_generic_scope_and_inconsistent_tls_state_fail() -> None:
    with private_workspace() as root:
        spec = base_spec()
        spec["products"]["cucm"]["syslog"]["scope"] = "generic_service_syslog"
        with pytest.raises(RENDERER.SpecError, match="remote_audit_logging"):
            load_validated_spec(root, spec)
        spec = base_spec()
        spec["products"]["cucm"]["syslog"].update(
            transport="tcp",
            tls_authentication="unidirectional_x509",
            trust_requirements_reviewed=True,
        )
        with pytest.raises(RENDERER.SpecError, match="enabled && transport == tls"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize(
    ("cms_mode", "cmm_mode"),
    [
        ("exact_host", "exact_ip"),
        ("exact_ip", "exact_host"),
        ("exact_host", "dedicated_port"),
        ("dedicated_port", "exact_host"),
        ("exact_ip", "dedicated_port"),
        ("dedicated_port", "exact_ip"),
    ],
)
def test_cms_cmm_mixed_classifier_modes_fail_closed(cms_mode: str, cmm_mode: str) -> None:
    values = {"exact_host": "cms.example.invalid", "exact_ip": "192.0.2.10", "dedicated_port": 1514}
    with private_workspace() as root:
        spec = base_spec()
        spec["products"]["cms"]["syslog"]["classifier"] = {"mode": cms_mode, "value": values[cms_mode]}
        spec["products"]["meeting_management"]["classifier"] = {"mode": cmm_mode, "value": values[cmm_mode]}
        with pytest.raises(RENDERER.SpecError, match="mixed modes"):
            load_validated_spec(root, spec)


def test_classifier_overlap_regex_and_broad_values_fail_closed() -> None:
    with private_workspace() as root:
        spec = base_spec()
        spec["products"]["meeting_management"]["classifier"] = copy.deepcopy(
            spec["products"]["cms"]["syslog"]["classifier"]
        )
        with pytest.raises(RENDERER.SpecError, match="overlap"):
            load_validated_spec(root, spec)
        spec = base_spec()
        spec["products"]["cms"]["syslog"]["classifier"] = {"mode": "exact_host", "value": ".*"}
        with pytest.raises(RENDERER.SpecError, match="wildcard or regex"):
            load_validated_spec(root, spec)


def test_expressway_cms_and_cmm_protocol_profiles_fail_closed() -> None:
    with private_workspace() as root:
        mutations = []
        spec = base_spec()
        spec["products"]["expressway"]["syslog"]["transport"] = "tcp"
        mutations.append(spec)
        spec = base_spec()
        spec["products"]["expressway"]["syslog"]["port"] = 514
        mutations.append(spec)
        spec = base_spec()
        spec["products"]["cms"]["syslog"]["wire_protocol"] = "udp"
        mutations.append(spec)
        spec = base_spec()
        spec["products"]["cms"]["syslog"]["tls_server_prefix"] = False
        mutations.append(spec)
        spec = base_spec()
        spec["products"]["meeting_management"]["system_syslog"]["tls_version"] = "TLS1.3"
        mutations.append(spec)
        spec = base_spec()
        spec["products"]["meeting_management"]["audit_syslog"]["receiver_max_bytes"] = 4096
        mutations.append(spec)
        for candidate in mutations:
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, candidate)


@pytest.mark.parametrize(
    ("field", "impostor"),
    [
        ("cdr.header_rows", 2.0),
        ("cdr.header_rows", True),
        ("cdr.record_count", 1.0),
        ("cucm.receiver_port", 6514.0),
        ("expressway.port", 6514.0),
        ("cms.classifier_port", 1514.0),
        ("cmm.classifier_port", 1515.0),
        ("cmm.receiver_max_bytes", 8192.0),
        ("cmm.receiver_max_bytes", True),
        ("cmm.planned_server_count", 1.0),
    ],
)
def test_integer_constants_reject_bool_and_float_impostors(field: str, impostor: Any) -> None:
    with private_workspace() as root:
        spec = base_spec()
        if field.startswith("cdr."):
            set_flat_file_evidence(spec, root, "cdr")
            spec["products"]["cucm"]["cdr"]["evidence"][field.split(".", 1)[1]] = impostor
        elif field == "cucm.receiver_port":
            spec["products"]["cucm"]["syslog"]["receiver_port"] = impostor
        elif field == "expressway.port":
            spec["products"]["expressway"]["syslog"]["port"] = impostor
        elif field == "cms.classifier_port":
            spec["products"]["cms"]["syslog"]["classifier"]["value"] = impostor
        elif field == "cmm.classifier_port":
            spec["products"]["meeting_management"]["classifier"]["value"] = impostor
        elif field == "cmm.receiver_max_bytes":
            spec["products"]["meeting_management"]["audit_syslog"]["receiver_max_bytes"] = impostor
        else:
            spec["products"]["meeting_management"]["audit_syslog"]["planned_server_count"] = impostor
        with pytest.raises(RENDERER.SpecError):
            load_validated_spec(root, spec)


@pytest.mark.parametrize("field", ["sanitized", "raw_event_values_included", "field_presence", "tag_presence"])
def test_cim_evidence_rejects_integer_boolean_impostors(field: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        evidence = make_cim_evidence(root, spec, "authentication")
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        if field == "sanitized":
            payload[field] = 1
        elif field == "raw_event_values_included":
            payload[field] = 0
        elif field == "field_presence":
            payload[field][next(iter(payload[field]))] = 1
        else:
            payload[field][next(iter(payload[field]))] = 1
        write_json(evidence, payload)
        spec["cim"]["authentication"]["evidence_sha256"] = sha256(evidence)
        with pytest.raises(RENDERER.SpecError, match="exactly match"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize("field", ["sanitized", "raw_event_values_included", "receiver_max_bytes"])
def test_cmm_evidence_rejects_bool_int_and_float_impostors(field: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        evidence = make_cmm_evidence(root, spec)
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload[field] = {"sanitized": 1, "raw_event_values_included": 0}.get(field, 8192.0)
        write_json(evidence, payload)
        route = spec["products"]["meeting_management"]["audit_syslog"]
        route["evidence_sha256"] = sha256(evidence)
        with pytest.raises(RENDERER.SpecError, match="exactly match"):
            load_validated_spec(root, spec)


def test_default_tls_profiles_emit_gaps_and_never_plaintext_vendor_ports() -> None:
    with private_workspace() as root:
        validated = load_validated_spec(root, base_spec())
        handoff = RENDERER.build_handoff_plan(validated, root / "bundle")
        argv = next(row["commands"][0] for row in handoff["sections"] if row["name"] == "collaboration-syslog")
        joined = " ".join(argv)
        assert "cisco_ms:tcp:" not in joined
        assert "cisco_mm:tcp:" not in joined
        assert "source-tls" not in joined
        gaps = {row["id"] for row in RENDERER.build_gaps(validated)["gaps"]}
        assert {
            "cucm_sc4s_listener",
            "expressway_sc4s_tls_listener",
            "cms_sc4s_tls_listener",
            "cmm_sc4s_tls_listener",
        } <= gaps


@pytest.mark.parametrize("product", ["cucm", "expressway"])
@pytest.mark.parametrize(
    ("enabled", "transport", "trust", "accepted"),
    [
        (True, "tls", True, True),
        (True, "tls", False, False),
        (False, "tls", False, True),
        (False, "tls", True, False),
        (True, "udp", False, True),
        (True, "udp", True, False),
        (False, "udp", False, True),
        (False, "udp", True, False),
    ],
)
def test_cucm_and_expressway_trust_is_exactly_enabled_tls(
    product: str,
    enabled: bool,
    transport: str,
    trust: bool,
    accepted: bool,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        if product == "cucm":
            route = spec["products"]["cucm"]["syslog"]
            route.update(
                enabled=enabled,
                transport=transport,
                receiver_port=6514 if transport == "tls" else 514,
                tls_authentication="unidirectional_x509" if transport == "tls" else "none",
                trust_requirements_reviewed=trust,
            )
        else:
            route = spec["products"]["expressway"]["syslog"]
            route.update(
                enabled=enabled,
                transport=transport,
                format="ietf",
                port=6514 if transport == "tls" else 514,
                trust_requirements_reviewed=trust,
            )
        if accepted:
            validated = load_validated_spec(root, spec)
            readiness_path = f"{product}.syslog"
            readiness = {
                row["path"]: row for row in RENDERER.build_readiness(validated)["routes"]
            }[readiness_path]
            assert readiness["operator_asserted"] is (enabled and transport == "tls")
        else:
            with pytest.raises(RENDERER.SpecError, match="enabled && transport == tls"):
                load_validated_spec(root, spec)


def disable_all_syslog_routes(spec: dict[str, Any]) -> None:
    spec["products"]["cucm"]["syslog"].update(
        enabled=False,
        trust_requirements_reviewed=False,
    )
    spec["products"]["expressway"]["syslog"].update(
        enabled=False,
        trust_requirements_reviewed=False,
    )
    spec["products"]["cms"]["syslog"]["enabled"] = False
    for name in ("system_syslog", "audit_syslog"):
        spec["products"]["meeting_management"][name].update(
            enabled=False,
            planned_server_count=0,
            evidence_path="",
            evidence_sha256="",
        )


def test_all_disabled_syslog_routes_have_no_listener_gap_or_sc4s_child_command() -> None:
    with private_workspace() as root:
        spec = base_spec()
        disable_all_syslog_routes(spec)
        validated = load_validated_spec(root, spec)
        sc4s = RENDERER.build_sc4s_plan(validated)
        assert {row["listener_readiness"] for row in sc4s["routes"]} == {"disabled"}
        readiness = {row["path"]: row for row in RENDERER.build_readiness(validated)["routes"]}
        for path in (
            "cucm.syslog",
            "expressway.syslog",
            "cms.syslog",
            "meeting_management.system_syslog",
            "meeting_management.audit_syslog",
        ):
            assert readiness[path]["status"] == "disabled"
            assert readiness[path]["operator_asserted"] is False
        assert readiness["cucm.syslog"]["sc4s_listener_gap"] is False
        assert readiness["expressway.syslog"]["sc4s_tls_listener_gap"] is False
        assert readiness["cms.syslog"]["sc4s_tls_listener_gap"] is False
        assert readiness["meeting_management.system_syslog"]["sc4s_tls_listener_gap"] is False
        assert readiness["meeting_management.audit_syslog"]["sc4s_tls_listener_gap"] is False
        gap_ids = {row["id"] for row in RENDERER.build_gaps(validated)["gaps"]}
        assert not gap_ids & {
            "cucm_sc4s_listener",
            "expressway_sc4s_tls_listener",
            "cms_sc4s_tls_listener",
            "cmm_sc4s_tls_listener",
        }
        handoff = RENDERER.build_handoff_plan(validated, root / "bundle")
        section = next(row for row in handoff["sections"] if row["name"] == "collaboration-syslog")
        assert section["commands"] == []


def test_mixed_disabled_tls_and_enabled_plaintext_routes_are_consistent() -> None:
    with private_workspace() as root:
        spec = base_spec()
        disable_all_syslog_routes(spec)
        cms = spec["products"]["cms"]["syslog"]
        cms.update(enabled=True, wire_protocol="tcp", tls_server_prefix=False)
        validated = load_validated_spec(root, spec)
        routes = {row["product"]: row for row in RENDERER.build_sc4s_plan(validated)["routes"]}
        assert routes["expressway"]["listener_readiness"] == "disabled"
        assert routes["cms"]["listener_readiness"] == "planned_render_handoff"
        assert routes["meeting_management"]["listener_readiness"] == "disabled"
        gaps = {row["id"] for row in RENDERER.build_gaps(validated)["gaps"]}
        assert "cms_sc4s_tls_listener" not in gaps
        handoff = RENDERER.build_handoff_plan(validated, root / "bundle")
        argv = next(row["commands"][0] for row in handoff["sections"] if row["name"] == "collaboration-syslog")
        assert "cisco_ms:tcp:1514" in argv


def test_cmm_system_and_audit_enablement_is_independent_and_metadata_never_qualifies_sample() -> None:
    with private_workspace() as root:
        spec = base_spec()
        audit = spec["products"]["meeting_management"]["audit_syslog"]
        audit.update(enabled=False, planned_server_count=0, evidence_path="", evidence_sha256="")
        validated = load_validated_spec(root, spec)
        plan = RENDERER.build_sc4s_plan(validated)
        cmm = next(row for row in plan["routes"] if row["product"] == "meeting_management")
        assert cmm["system_enabled"] is True
        assert cmm["audit_enabled"] is False
        assert cmm["sourcetypes"] == ["cisco:mm:system:*"]
        rows = {row["path"]: row for row in RENDERER.build_readiness(validated)["routes"]}
        assert rows["meeting_management.system_syslog"]["status"] == "planned_render_handoff"
        assert rows["meeting_management.system_syslog"]["local_sample_validated"] is False
        assert rows["meeting_management.audit_syslog"]["status"] == "disabled"


@pytest.mark.parametrize(
    "route_path",
    ["cucm.axl", "expressway.cdr_readiness", "expressway.media_readiness"],
)
def test_optional_readiness_operator_metadata_never_upgrades_or_accepts_file_evidence(route_path: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        if route_path == "cucm.axl":
            route = spec["products"]["cucm"]["axl"]
        elif route_path.endswith("cdr_readiness"):
            route = spec["products"]["expressway"]["cdr_readiness"]
        else:
            route = spec["products"]["expressway"]["media_readiness"]
        route["enabled"] = True
        route["operator_metadata"] = {
            "qualifying_search": "search index=netops sourcetype=cisco:mm:audit | head 1",
            "asserted_fields": ["not_observed_at_all"],
            "observation_note": "Operator assertion only; no event-derived schema exists.",
        }
        validated = load_validated_spec(root, spec)
        row = next(item for item in RENDERER.build_readiness(validated)["routes"] if item["path"] == route_path)
        assert row["status"] == "planned_render_handoff"
        assert row["local_sample_validated"] is False
        assert row["operator_asserted"] is True

        arbitrary = root / "arbitrary.txt"
        arbitrary.write_text(SKILL_DIR.joinpath("SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
        route["evidence_path"] = arbitrary.name
        route["evidence_sha256"] = sha256(arbitrary)
        with pytest.raises(RENDERER.SpecError, match="unknown field"):
            load_validated_spec(root, spec)


@pytest.mark.parametrize(
    "search",
    [
        'index="*" sourcetype="*" | stats count',
        "index=* sourcetype=* | stats count",
        "index=foo sourcetype=bar | mcollect index=summary",
        "index=foo sourcetype=bar | metasearch",
        "`unsafe_macro` index=foo sourcetype=bar",
        "index=foo sourcetype=bar [ search index=baz sourcetype=qux ]",
        "index=foo OR index=bar sourcetype=baz | stats count",
        "evilcommand index=netops sourcetype=cisco:mm:audit | stats count",
    ],
)
def test_safe_spl_rejects_broad_write_macro_subsearch_and_custom_generators(search: str) -> None:
    with pytest.raises(RENDERER.SpecError):
        RENDERER.validate_safe_search(search, "canary.search")


def make_cim_evidence(root: Path, spec: dict[str, Any], model: str) -> Path:
    requirements = RENDERER.CIM_REQUIREMENTS[model]
    search = "search index=netops sourcetype=cisco:mm:audit | head 20"
    fields = sorted(requirements["fields"])
    tags = sorted(requirements["tags"])
    evidence = {
        "schema": "cisco-collaboration-setup/cim-evidence/v1",
        "model": requirements["model"],
        "route": "meeting_management.audit_syslog",
        "index": "netops",
        "sourcetype": "cisco:mm:audit",
        "qualifying_search_sha256": hashlib.sha256(search.encode("utf-8")).hexdigest(),
        "required_fields": fields,
        "required_tags": tags,
        "field_presence": {field: True for field in fields},
        "tag_presence": {tag: True for tag in tags},
        "sanitized": True,
        "raw_event_values_included": False,
    }
    path = root / f"{model}-cim-evidence.json"
    write_json(path, evidence)
    block = spec["cim"][model]
    block.update(
        enabled=True,
        qualifying_search=search,
        verified_fields=fields,
        evidence_path=path.name,
        evidence_sha256=sha256(path),
    )
    return path


def make_cmm_evidence(root: Path, spec: dict[str, Any], route_name: str = "audit_syslog") -> Path:
    route = spec["products"]["meeting_management"][route_name]
    route_path = f"meeting_management.{route_name}"
    evidence = {
        "schema": "cisco-collaboration-setup/cmm-syslog-evidence/v1",
        "route": route_path,
        "index": "netops",
        "sourcetype": route["sourcetype"],
        "wire_protocol": route["wire_protocol"],
        "tls_version": route["tls_version"],
        "receiver_max_bytes": 8192,
        "planned_server_count": route["planned_server_count"],
        "sanitized": True,
        "raw_event_values_included": False,
    }
    path = root / f"cmm-{route_name}-evidence.json"
    write_json(path, evidence)
    route["evidence_path"] = path.name
    route["evidence_sha256"] = sha256(path)
    return path


def enable_partner_4640(spec: dict[str, Any], root: Path) -> None:
    entitlement = root / "entitlement-review.txt"
    package = root / "package-metadata.txt"
    entitlement.write_text("Sanitized entitlement review completed.\n", encoding="utf-8")
    package.write_text("Sanitized package metadata inspection completed.\n", encoding="utf-8")
    entitlement.chmod(0o600)
    package.chmod(0o600)

    def selection(app_id: str, version: str, tier: str) -> dict[str, Any]:
        return {
            "app_id": app_id,
            "version": version,
            "tier": tier,
            "entitlement_reviewed": True,
            "license_assumption": "none",
            "entitlement_evidence_path": entitlement.name,
            "entitlement_evidence_sha256": sha256(entitlement),
            "package_metadata_evidence_path": package.name,
            "package_metadata_evidence_sha256": sha256(package),
        }

    spec["partner_packages"] = {
        "mode": "evidence_only",
        "selections": [
            selection("669", "8.4.2", "search-tier"),
            selection("4640", "1.2.9", "search-tier"),
        ],
    }


@pytest.mark.parametrize(
    ("version", "accepted"),
    [
        ("10.4", True),
        ("10.4.0", True),
        ("10.4.1", False),
        ("10.5", False),
        ("10.6", False),
        ("11.0", False),
        ("99.0", False),
        ("01.4", False),
        ("10.04", False),
        (" 10.4", False),
        ("10.4 ", False),
        ("+10.4", False),
        ("-10.4", False),
        ("10.4.0.0", False),
        ("10.4-beta", False),
        ("10.4+build", False),
        ("v10.4", False),
        ("10", False),
        ("١٠.٤", False),
    ],
)
def test_partner_4640_strict_platform_maximum(version: str, accepted: bool) -> None:
    with private_workspace() as root:
        spec = base_spec()
        spec["project"]["splunk_platform_version"] = version
        enable_partner_4640(spec, root)
        if accepted:
            validated = load_validated_spec(root, spec)
            assert [row["app_id"] for row in validated["partner_packages"]["selections"]] == ["669", "4640"]
        else:
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, spec)


@pytest.mark.parametrize("model", ["authentication", "change"])
def test_cim_allowlist_accepts_only_cmm_audit_candidate_and_never_claims_live(model: str) -> None:
    with private_workspace() as root:
        spec = base_spec()
        make_cim_evidence(root, spec, model)
        validated = load_validated_spec(root, spec)
        plan, _spl = RENDERER.build_cim_plan(validated)
        assert plan["telephony_cim_claimed"] is False
        assert plan["voip_cim_claimed"] is False
        assert plan["mappings"][0]["status"] == "unverified_candidate"
        assert plan["mappings"][0]["live_verified"] is False
        assert plan["mappings"][0]["qualifying_search_persisted"] is False
        assert "qualifying_search" not in plan["mappings"][0]


def test_cim_rejects_unrelated_index_fabricated_fields_and_evidence_mismatch() -> None:
    with private_workspace() as root:
        for mutation in ("index", "field", "evidence"):
            spec = base_spec()
            evidence = make_cim_evidence(root, spec, "authentication")
            block = spec["cim"]["authentication"]
            if mutation == "index":
                block["qualifying_search"] = "search index=other sourcetype=cisco:mm:audit | head 20"
            elif mutation == "field":
                block["verified_fields"][-1] = "fabricated_field"
            else:
                payload = json.loads(evidence.read_text(encoding="utf-8"))
                payload["field_presence"]["user"] = False
                write_json(evidence, payload)
                block["evidence_sha256"] = sha256(evidence)
            with pytest.raises(RENDERER.SpecError):
                load_validated_spec(root, spec)


@pytest.mark.parametrize("evidence_class", ["cdr_cmr", "cim", "partner", "cmm"])
def test_historical_evidence_requires_trusted_spec_and_optional_external_digest(
    evidence_class: str,
) -> None:
    with private_workspace() as root:
        spec = base_spec()
        if evidence_class == "cdr_cmr":
            set_flat_file_evidence(spec, root, "cdr")
            set_flat_file_evidence(spec, root, "cmr")
        elif evidence_class == "cim":
            make_cim_evidence(root, spec, "authentication")
        elif evidence_class == "partner":
            spec["project"]["splunk_platform_version"] = "10.4"
            enable_partner_4640(spec, root)
        else:
            make_cmm_evidence(root, spec)
        spec_path = write_spec(root, spec)
        out = root / "bundle"
        rendered = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--json",
        )
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr

        bare = validate_output(out)
        assert bare.returncode == 2
        assert "historical/local evidence claims require --spec" in bare.stdout + bare.stderr

        wrong_spec = write_spec(root, base_spec(), "wrong-spec.json")
        wrong = validate_output(out, spec=wrong_spec)
        assert wrong.returncode == 2
        assert "source-spec commitment" in wrong.stdout + wrong.stderr

        trusted_digest = sha256(spec_path)
        trusted = validate_output(
            out,
            spec=spec_path,
            expected_spec_sha256=trusted_digest,
        )
        assert trusted.returncode == 0, trusted.stdout + trusted.stderr
        payload = json.loads(trusted.stdout)
        assert payload["status"] == "offline_structure_and_provenance_checked"
        assert payload["provenance_status"] == "verified_against_trusted_spec_and_local_evidence"

        wrong_digest = validate_output(
            out,
            spec=spec_path,
            expected_spec_sha256="0" * 64,
        )
        assert wrong_digest.returncode == 2
        assert "does not match --expected-spec-sha256" in wrong_digest.stdout + wrong_digest.stderr


def test_base_bundle_without_historical_evidence_allows_structural_validation() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        result = validate_output(out)
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "offline_structure_checked"
        assert payload["provenance_status"] == "not_required"


@pytest.mark.parametrize(
    "search",
    [
        "search index=netops sourcetype=cisco:mm:audit | search user=alice@example.com",
        'search index=netops sourcetype=cisco:mm:audit | eval user="alice@example.com"',
        'search index=netops sourcetype=cisco:mm:audit | where user="alice@example.com"',
    ],
)
def test_cim_identifier_literals_remain_outside_every_rendered_artifact(search: str) -> None:
    literal = "alice@example.com"
    with private_workspace() as root:
        spec = base_spec()
        evidence = make_cim_evidence(root, spec, "authentication")
        block = spec["cim"]["authentication"]
        block["qualifying_search"] = search
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload["qualifying_search_sha256"] = hashlib.sha256(search.encode("utf-8")).hexdigest()
        write_json(evidence, payload)
        block["evidence_sha256"] = sha256(evidence)
        spec_path = write_spec(root, spec)
        out = root / "bundle"
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--json",
        )
        assert result.returncode == 2
        assert literal not in result.stdout
        assert not out.exists()


def test_privacy_spl_explicitly_removes_raw_then_preserves_time_and_tamper_fails() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        relative = "dashboards/cisco-collaboration-dashboard.spl"
        path = out / relative
        original = path.read_text(encoding="utf-8")
        exact = "| fields _time collaboration_route\n| fields - _raw\n| timechart"
        assert exact in original
        for tampered in (
            original.replace("| fields - _raw\n", ""),
            original.replace(
                "| fields _time collaboration_route\n| fields - _raw\n",
                "| fields - _raw\n| fields _time collaboration_route\n",
            ),
        ):
            path.write_text(tampered, encoding="utf-8")
            update_manifest_hash(out, relative)
            result = validate_output(out)
            assert result.returncode != 0
            path.write_text(original, encoding="utf-8")
            update_manifest_hash(out, relative)
            assert validate_output(out).returncode == 0


@pytest.mark.parametrize(
    ("relative", "mutate"),
    [
        ("readiness/readiness-report.json", lambda value: value["routes"][0].update(status="complete")),
        ("evidence/cms-xml-cdr.json", lambda value: value.update(receiver_implementation="implemented")),
        ("sc4s/classifier-plan.json", lambda value: value["routes"][0].update(sourcetypes=["spoofed"])),
        ("handoffs/handoff-plan.json", lambda value: value["sections"][0].update(disposition="execute")),
    ],
)
def test_semantic_tamper_fails_even_when_attacker_rehashes_manifest(relative: str, mutate) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        path = out / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)
        update_manifest_hash(out, relative)
        result = validate_output(out)
        assert result.returncode != 0


def test_manifest_rehash_cannot_bypass_renderer_marker_commitment() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        relative = "readiness/readiness-report.md"
        path = out / relative
        path.write_text(path.read_text(encoding="utf-8") + "\nAll routes complete.\n", encoding="utf-8")
        update_manifest_hash(out, relative)
        result = validate_output(out)
        assert result.returncode == 2
        assert "marker commitment" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "plan",
        "handoff_and_plan",
        "sc4s_and_plan",
        "readiness_and_plan",
        "index",
        "privacy",
        "evidence",
        "cim",
        "gaps",
    ],
)
def test_schema_version_float_is_rejected_after_coherent_rehash(case: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        changed: list[str] = []

        def set_float(relative: str, nested_key: str | None = None) -> None:
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            target = value if nested_key is None else value[nested_key]
            target["schema_version"] = 1.0
            write_json(out / relative, value)
            changed.append(relative)

        if case == "plan":
            set_float("plan.json")
        elif case == "handoff_and_plan":
            set_float("handoffs/handoff-plan.json")
            set_float("plan.json", "handoffs")
        elif case == "sc4s_and_plan":
            set_float("sc4s/classifier-plan.json")
            set_float("plan.json", "sc4s")
        elif case == "readiness_and_plan":
            set_float("readiness/readiness-report.json")
            set_float("plan.json", "readiness")
        else:
            relative_by_case = {
                "index": "readiness/index-plan.json",
                "privacy": "privacy/privacy-plan.json",
                "evidence": "evidence/requirements.json",
                "cim": "cim/mappings.json",
                "gaps": "gaps/gap-register.json",
            }
            set_float(relative_by_case[case])
        coherent_rehash(out, *changed)
        result = validate_output(out)
        assert result.returncode == 2, case
        assert "schema_version must be integer 1" in result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "sc4s_route_apply_commands",
        "readiness_route_live_validation",
        "index_row_apply_commands",
        "flat_file_raw_events_exported",
    ],
)
def test_nested_unknown_claim_and_executable_keys_fail_after_coherent_rehash(case: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        changed: list[str] = []
        if case == "sc4s_route_apply_commands":
            for relative, nested in (
                ("sc4s/classifier-plan.json", None),
                ("plan.json", "sc4s"),
            ):
                value = json.loads((out / relative).read_text(encoding="utf-8"))
                target = value if nested is None else value[nested]
                target["routes"][0]["apply_commands"] = [["bash", "tool", "--apply-host"]]
                write_json(out / relative, value)
                changed.append(relative)
        elif case == "readiness_route_live_validation":
            for relative, nested in (
                ("readiness/readiness-report.json", None),
                ("plan.json", "readiness"),
            ):
                value = json.loads((out / relative).read_text(encoding="utf-8"))
                target = value if nested is None else value[nested]
                target["routes"][0]["live_validation_performed"] = True
                write_json(out / relative, value)
                changed.append(relative)
        elif case == "index_row_apply_commands":
            relative = "readiness/index-plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["indexes"][0]["apply_commands"] = [["bash", "tool", "--apply-host"]]
            write_json(out / relative, value)
            changed.append(relative)
        else:
            relative = "evidence/requirements.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["flat_file_paths"][0]["raw_events_exported"] = True
            write_json(out / relative, value)
            changed.append(relative)
        coherent_rehash(out, *changed)
        result = validate_output(out)
        assert result.returncode == 2, case
        assert "unknown field" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "sc4s_product",
        "readiness_path",
        "index_route",
        "evidence_path",
        "gap_id",
    ],
)
def test_duplicate_projection_identities_fail_after_coherent_rehash(case: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        changed: list[str] = []
        if case == "sc4s_product":
            for relative, nested in (
                ("sc4s/classifier-plan.json", None),
                ("plan.json", "sc4s"),
            ):
                value = json.loads((out / relative).read_text(encoding="utf-8"))
                target = value if nested is None else value[nested]
                target["routes"].append(copy.deepcopy(target["routes"][0]))
                write_json(out / relative, value)
                changed.append(relative)
        elif case == "readiness_path":
            readiness_relative = "readiness/readiness-report.json"
            readiness = json.loads((out / readiness_relative).read_text(encoding="utf-8"))
            readiness["routes"].append(copy.deepcopy(readiness["routes"][0]))
            write_json(out / readiness_relative, readiness)
            changed.append(readiness_relative)
            plan_relative = "plan.json"
            plan = json.loads((out / plan_relative).read_text(encoding="utf-8"))
            plan["readiness"]["routes"].append(copy.deepcopy(plan["readiness"]["routes"][0]))
            write_json(out / plan_relative, plan)
            changed.append(plan_relative)
            markdown_relative = "readiness/readiness-report.md"
            (out / markdown_relative).write_text(
                RENDERER.markdown_readiness(readiness), encoding="utf-8"
            )
            changed.append(markdown_relative)
        elif case == "index_route":
            relative = "readiness/index-plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["indexes"].append(copy.deepcopy(value["indexes"][0]))
            write_json(out / relative, value)
            changed.append(relative)
        elif case == "evidence_path":
            relative = "evidence/requirements.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["flat_file_paths"].append(copy.deepcopy(value["flat_file_paths"][0]))
            write_json(out / relative, value)
            changed.append(relative)
        else:
            relative = "gaps/gap-register.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["gaps"].append(copy.deepcopy(value["gaps"][0]))
            write_json(out / relative, value)
            changed.append(relative)
            markdown_relative = "gaps/gap-register.md"
            (out / markdown_relative).write_text(
                RENDERER.markdown_gaps(value), encoding="utf-8"
            )
            changed.append(markdown_relative)
        coherent_rehash(out, *changed)
        result = validate_output(out)
        assert result.returncode == 2, case
        assert "duplicate" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "relative",
    [
        "privacy/privacy-plan.md",
        "dashboards/starter-search-readiness.md",
        "sc4s/classifier-review.md",
        "evidence/cdr-cmr.md",
        "handoffs/roomos-webex.md",
        "handoffs/roomos-thousandeyes.md",
        "handoffs/broadworks.md",
    ],
)
def test_renderer_owned_markdown_replacement_fails_after_coherent_rehash(relative: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        (out / relative).write_text("# Replacement\n\nOperator-authored text.\n", encoding="utf-8")
        coherent_rehash(out, relative)
        result = validate_output(out)
        assert result.returncode == 2, relative
        assert "deterministic renderer-owned template" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("relative", "replacement"),
    [
        (
            "dashboards/cisco-collaboration-dashboard.spl",
            "write_capable_macro\n",
        ),
        ("cim/mappings.spl", "write_capable_macro\n"),
        ("cim/mappings.spl", ""),
    ],
)
def test_spl_macro_or_empty_rewrite_fails_after_coherent_rehash(
    relative: str,
    replacement: str,
) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        if relative.startswith("dashboards/"):
            replacement += (out / relative).read_text(encoding="utf-8")
        (out / relative).write_text(replacement, encoding="utf-8")
        coherent_rehash(out, relative)
        result = validate_output(out)
        assert result.returncode == 2, (relative, replacement)
        assert "Traceback" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("case", "malformed"),
    [
        ("sc4s", None),
        ("sc4s", {}),
        ("readiness", None),
        ("readiness", {}),
        ("index", None),
        ("index", {}),
        ("evidence", None),
        ("evidence", {}),
        ("cim", None),
        ("cim", {}),
    ],
)
def test_malformed_projection_containers_return_controlled_rc2(
    case: str,
    malformed: Any,
) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        changed: list[str] = []
        if case in {"sc4s", "readiness"}:
            relative = (
                "sc4s/classifier-plan.json"
                if case == "sc4s"
                else "readiness/readiness-report.json"
            )
            key = "routes"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value[key] = malformed
            write_json(out / relative, value)
            changed.append(relative)
            plan_relative = "plan.json"
            plan = json.loads((out / plan_relative).read_text(encoding="utf-8"))
            plan[case][key] = malformed
            write_json(out / plan_relative, plan)
            changed.append(plan_relative)
        else:
            relative, key = {
                "index": ("readiness/index-plan.json", "indexes"),
                "evidence": ("evidence/requirements.json", "flat_file_paths"),
                "cim": ("cim/mappings.json", "mappings"),
            }[case]
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value[key] = malformed
            write_json(out / relative, value)
            changed.append(relative)
        coherent_rehash(out, *changed)
        result = validate_output(out)
        assert result.returncode == 2, (case, malformed)
        assert "must be a list" in result.stdout + result.stderr
        assert "Traceback" not in result.stdout + result.stderr
        assert json.loads(result.stdout)["status"] == "error"


@pytest.mark.parametrize("family", ["cdr", "cmr"])
def test_four_artifact_local_qualification_forge_fails_marker_commitment(family: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        readiness_relative = "readiness/readiness-report.json"
        readiness = json.loads((out / readiness_relative).read_text(encoding="utf-8"))
        readiness_row = next(row for row in readiness["routes"] if row["path"] == f"cucm.{family}")
        readiness_row.update(
            status="locally_evidence_qualified",
            planned=True,
            local_sample_validated=True,
            operator_asserted=True,
        )
        write_json(out / readiness_relative, readiness)

        plan_relative = "plan.json"
        plan = json.loads((out / plan_relative).read_text(encoding="utf-8"))
        plan_row = next(row for row in plan["readiness"]["routes"] if row["path"] == f"cucm.{family}")
        plan_row.update(
            status="locally_evidence_qualified",
            planned=True,
            local_sample_validated=True,
            operator_asserted=True,
        )
        write_json(out / plan_relative, plan)

        evidence_relative = "evidence/requirements.json"
        evidence = json.loads((out / evidence_relative).read_text(encoding="utf-8"))
        evidence_row = next(row for row in evidence["flat_file_paths"] if row["path"] == f"cucm.{family}")
        evidence_row.update(
            enabled=True,
            status="locally_evidence_qualified",
            planned=True,
            local_sample_validated=True,
            operator_asserted=True,
            sample_sha256="a" * 64,
            record_count=1,
            observed_fields=["fabricatedField"],
            independently_evidenced=True,
        )
        write_json(out / evidence_relative, evidence)

        index_relative = "readiness/index-plan.json"
        index_plan = json.loads((out / index_relative).read_text(encoding="utf-8"))
        index_row = next(row for row in index_plan["indexes"] if row["route"] == f"cucm_{family}")
        index_row.update(
            enabled=True,
            status="locally_evidence_qualified",
            sourcetype=f"cisco:cucm:{family}",
        )
        write_json(out / index_relative, index_plan)

        for relative in (readiness_relative, plan_relative, evidence_relative, index_relative):
            update_manifest_hash(out, relative)
        result = validate_output(out)
        assert result.returncode == 2
        assert "marker commitment" in result.stdout + result.stderr


def test_fabricated_partner_app_fails_even_after_coherent_local_rehash() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        relative = "partners/package-review.json"
        review = json.loads((out / relative).read_text(encoding="utf-8"))
        review["mode"] = "evidence_only"
        review["selections"] = [
            {
                "app_id": "9999",
                "version": "1.0.0",
                "tier": "search-tier",
                "publisher": "Splunk",
                "ownership": "official TA",
                "support": "Splunk-supported",
                "entitlement": "included",
                "entitlement_evidence_sha256": "a" * 64,
                "package_metadata_evidence_sha256": "b" * 64,
                "installation_command_generated": False,
            }
        ]
        write_json(out / relative, review)
        update_manifest_hash(out, relative)
        update_marker_commitments(out, relative)
        result = validate_output(out)
        assert result.returncode == 2
        assert "partner allowlist" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "handoff_apply_commands",
        "sc4s_apply_markdown",
        "cim_collect",
        "plan_sc4s_applied",
        "index_created",
        "live_evidence",
        "uccx_supported",
        "gaps_nonblocking",
        "cim_network_traffic",
        "privacy_raw_export",
        "plan_device_mutation",
        "broadworks_live_collector",
        "cms_live_receiver",
        "readiness_markdown_complete",
        "gaps_markdown_resolved",
        "metadata_bool_int_swap",
    ],
)
def test_impossible_semantics_fail_even_after_manifest_and_marker_rehash(case: str) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        if case == "handoff_apply_commands":
            relative = "handoffs/handoff-plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["sections"][0]["apply_commands"] = [["bash", "tool", "--apply-host"]]
            write_json(out / relative, value)
        elif case == "sc4s_apply_markdown":
            relative = "handoffs/sc4s.md"
            (out / relative).write_text("# Apply\n\nRun `--apply-host`.\n", encoding="utf-8")
        elif case == "cim_collect":
            relative = "cim/mappings.spl"
            (out / relative).write_text("search index=netops sourcetype=cisco:mm:audit | collect index=summary\n", encoding="utf-8")
        elif case == "plan_sc4s_applied":
            relative = "plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["sc4s"]["generated_config_applied"] = True
            write_json(out / relative, value)
        elif case == "index_created":
            relative = "readiness/index-plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["index_creation_performed"] = True
            write_json(out / relative, value)
        elif case == "live_evidence":
            relative = "evidence/requirements.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["live_evidence_collected"] = True
            write_json(out / relative, value)
        elif case == "uccx_supported":
            relative = "evidence/uccx-ucce.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value.update(status="supported", ta="fabricated", collector="live", implementation_claimed=True)
            write_json(out / relative, value)
        elif case == "gaps_nonblocking":
            relative = "gaps/gap-register.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            for row in value["gaps"]:
                row["blocking"] = False
            write_json(out / relative, value)
        elif case == "cim_network_traffic":
            relative = "cim/mappings.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["network_traffic_inferred"] = True
            write_json(out / relative, value)
        elif case == "privacy_raw_export":
            relative = "privacy/privacy-plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["raw_events_exported"] = True
            write_json(out / relative, value)
        elif case == "plan_device_mutation":
            relative = "plan.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["device_mutation_performed"] = True
            write_json(out / relative, value)
        elif case == "broadworks_live_collector":
            relative = "evidence/broadworks.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value.update(status="supported", collector="live")
            write_json(out / relative, value)
        elif case == "cms_live_receiver":
            relative = "evidence/cms-xml-cdr.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value.update(receiver_implementation="live", implemented_by_this_skill=True)
            write_json(out / relative, value)
        elif case == "readiness_markdown_complete":
            relative = "readiness/readiness-report.md"
            (out / relative).write_text("# Complete\n\nAll routes validated.\n", encoding="utf-8")
        elif case == "gaps_markdown_resolved":
            relative = "gaps/gap-register.md"
            (out / relative).write_text("# Resolved\n\nNo gaps.\n", encoding="utf-8")
        else:
            relative = "metadata.json"
            value = json.loads((out / relative).read_text(encoding="utf-8"))
            value["live_service_calls"] = False
            write_json(out / relative, value)
        update_manifest_hash(out, relative)
        update_marker_commitments(out, relative)
        result = validate_output(out)
        assert result.returncode == 2, case


def test_duplicate_key_in_rendered_json_fails_strict_decode_even_when_rehashed() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        relative = "metadata.json"
        path = out / relative
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace('{\n  "api_version"', '{\n  "skill": "spoof",\n  "api_version"', 1), encoding="utf-8")
        update_manifest_hash(out, relative)
        result = validate_output(out)
        assert result.returncode != 0
        assert "duplicate JSON key" in result.stdout + result.stderr


def test_invalid_spec_and_symlink_output_create_no_bundle() -> None:
    with private_workspace() as root:
        spec = base_spec()
        spec["products"]["cms"]["syslog"]["unknown_field"] = True
        spec_path = write_spec(root, spec)
        out = root / "invalid-bundle"
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--json",
        )
        assert result.returncode != 0
        assert not out.exists()
        assert list(root.glob(".invalid-bundle.stage-*")) == []

        redirected = root / "redirected"
        redirected.mkdir(mode=0o700)
        symlink_out = root / "symlink-bundle"
        symlink_out.symlink_to(redirected, target_is_directory=True)
        valid_spec = write_spec(root, base_spec(), "valid.json")
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(valid_spec),
            "--output-dir",
            str(symlink_out),
            "--json",
        )
        assert result.returncode != 0
        assert list(redirected.iterdir()) == []


def test_midwrite_failure_cleans_only_unpublished_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    with private_workspace() as root:
        spec_path = write_spec(root, base_spec())
        out = root / "bundle"
        real_write = RENDERER.safe_write
        calls = 0

        def injected(stage: Path, relative: str, content: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected mid-write failure")
            real_write(stage, relative, content)

        monkeypatch.setattr(RENDERER, "safe_write", injected)
        args = SimpleNamespace(
            spec=str(spec_path),
            output_dir=str(out),
            dry_run=False,
            validate_only=False,
            replace_existing=False,
            json=True,
        )
        with pytest.raises(OSError, match="injected"):
            RENDERER.render(args)
        assert not out.exists()
        assert list(root.glob(".bundle.stage-*")) == []
        assert list(root.glob(".bundle.lock")) == []


def test_replacement_backup_is_path_bound_then_valid_after_reviewed_restore() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        original_inode = out.stat().st_ino
        spec_path = root / "spec.json"
        replaced = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--replace-existing",
            "--json",
        )
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        payload = json.loads(replaced.stdout)
        backup = Path(payload["backup_dir"])
        assert out.is_dir()
        assert backup.is_dir()
        assert backup.stat().st_ino == original_inode
        assert validate_output(out).returncode == 0
        in_place = validate_output(backup)
        assert in_place.returncode != 0
        assert "marker does not own this exact" in in_place.stdout + in_place.stderr

        new_hold = root / ".reviewed-new-output-hold"
        os.rename(out, new_hold)
        assert not out.exists()
        os.rename(backup, out)
        restored = validate_output(out)
        assert restored.returncode == 0, restored.stdout + restored.stderr


def test_qualified_existing_bundle_can_be_replaced_by_a_different_new_spec() -> None:
    with private_workspace() as root:
        old_spec = base_spec()
        set_flat_file_evidence(old_spec, root, "cdr")
        old_spec_path = write_spec(root, old_spec, "qualified-old.json")
        out = root / "bundle"
        initial = run_command(
            "bash", str(SETUP_PATH), "--spec", str(old_spec_path), "--output-dir", str(out), "--json"
        )
        assert initial.returncode == 0, initial.stdout + initial.stderr

        new_spec_path = write_spec(root, base_spec(), "new-spec.json")
        replaced = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(new_spec_path),
            "--output-dir",
            str(out),
            "--replace-existing",
            "--json",
        )
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        payload = json.loads(replaced.stdout)
        assert Path(payload["backup_dir"]).is_dir()
        assert validate_output(out).returncode == 0


def test_qualified_backup_restore_requires_original_trusted_spec_and_digest() -> None:
    with private_workspace() as root:
        old_spec = base_spec()
        set_flat_file_evidence(old_spec, root, "cdr")
        old_spec_path = write_spec(root, old_spec, "qualified-old.json")
        old_digest = sha256(old_spec_path)
        out = root / "bundle"
        initial = run_command(
            "bash", str(SETUP_PATH), "--spec", str(old_spec_path), "--output-dir", str(out), "--json"
        )
        assert initial.returncode == 0, initial.stdout + initial.stderr

        new_spec_path = write_spec(root, base_spec(), "replacement.json")
        replaced = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(new_spec_path),
            "--output-dir",
            str(out),
            "--replace-existing",
            "--json",
        )
        assert replaced.returncode == 0, replaced.stdout + replaced.stderr
        backup = Path(json.loads(replaced.stdout)["backup_dir"])
        hold = root / ".replacement-hold"
        os.rename(out, hold)
        os.rename(backup, out)

        bare = validate_output(out)
        assert bare.returncode == 2
        assert "historical/local evidence claims require --spec" in bare.stdout + bare.stderr
        trusted = validate_output(
            out,
            spec=old_spec_path,
            expected_spec_sha256=old_digest,
        )
        assert trusted.returncode == 0, trusted.stdout + trusted.stderr
        assert json.loads(trusted.stdout)["provenance_status"] == "verified_against_trusted_spec_and_local_evidence"


def test_publish_failure_after_backup_rename_rolls_original_back(monkeypatch: pytest.MonkeyPatch) -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        identity = RENDERER.existing_identity(out)
        stage = root / ".bundle.stage-injected"
        stage.mkdir(mode=0o700)
        real_rename = RENDERER.os.rename

        def failing_rename(source, destination):
            if Path(source) == stage and Path(destination) == out:
                raise OSError("injected publish failure")
            return real_rename(source, destination)

        monkeypatch.setattr(RENDERER.os, "rename", failing_rename)
        with pytest.raises(OSError, match="injected publish failure"):
            RENDERER.publish_staged_bundle(
                stage,
                out,
                replace_existing=True,
                inspected_identity=identity,
            )
        assert out.is_dir()
        assert out.stat().st_ino == identity[1]
        assert validate_output(out).returncode == 0
        assert list(root.glob(".bundle.backup-*")) == []


def test_stale_lock_and_uid_mismatch_fail_without_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    with private_workspace() as root:
        spec_path = write_spec(root, base_spec())
        out = root / "bundle"
        lock = root / ".bundle.lock"
        lock.write_text("stale\n", encoding="utf-8")
        lock.chmod(0o600)
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
            "--json",
        )
        assert result.returncode != 0
        assert not out.exists()
        lock.unlink()

        monkeypatch.setattr(RENDERER, "current_uid", lambda: os.getuid() + 1)
        with pytest.raises(RENDERER.SpecError, match="current user"):
            RENDERER.validated_output_path(out)


def test_child_sc4s_render_is_separate_and_parent_remains_valid() -> None:
    with private_workspace() as root:
        out, _ = render_bundle(root)
        handoff = json.loads((out / "handoffs/handoff-plan.json").read_text(encoding="utf-8"))
        assert handoff["child_output_privacy_status"] == "operator_hardening_required"
        section = next(row for row in handoff["sections"] if row["name"] == "collaboration-syslog")
        argv = section["commands"][0]
        child = Path(argv[argv.index("--output-dir") + 1])
        assert child.parent == out.parent
        assert child != out and out not in child.parents
        assert "separate sibling" in section["boundary"]
        assert "private sibling" not in section["boundary"]
        executed = run_command(*argv)
        assert executed.returncode == 0, executed.stdout + executed.stderr
        assert child.is_dir()
        assert validate_output(out).returncode == 0
        assert any(stat.S_IMODE(path.stat().st_mode) in {0o755, 0o644} for path in child.rglob("*"))


def test_source_ledger_required_claims_are_unique_current_and_commit_pinned() -> None:
    ledger = RENDERER.load_source_ledger()
    claims = {row["claim_id"]: row for row in ledger["sources"]}
    assert len(claims) == len(ledger["sources"])
    assert ledger["sc4s_upstream_commit"] == "f878a6e8031b07ae8777e97738b27afe735f118d"
    exact_paths = {
        "sc4s-ucm-parser-source": "package/shared/addons/cisco/app-cisco-cisco_ucm.conf",
        "sc4s-tvcs-parser-source": "package/shared/addons/cisco/app-syslog-cisco_tvcs.conf",
        "sc4s-cms-parser-source": "package/shared/addons/cisco/app-netsource-cisco_ms.conf",
        "sc4s-cmm-classifier-source": "package/shared/addons/cisco/app-netsource-cisco_mm.conf",
        "sc4s-cmm-parser-source": "package/shared/addons/cisco/app-syslog-cisco_mm.conf",
    }
    for claim_id, path in exact_paths.items():
        assert claims[claim_id]["url"].endswith(path)
        assert ledger["sc4s_upstream_commit"] in claims[claim_id]["url"]
    assert claims["cisco-cucm-15-remote-audit-syslog"]["source_version"] == "15 and SUs"
    assert "operator-selected port" in claims["cisco-cucm-15-remote-audit-syslog"]["claim"]
    assert "Positive Integer" in claims["cisco-cucm-cdr-15-cdr-fields"]["claim"]
    assert "origLegCallIdentifier" in claims["cisco-cucm-cdr-15-cdr-fields"]["claim"]
    assert claims["cisco-cucm-cdr-15-cdr-fields"]["source_date"] == "2026-04-09"
    assert "jitter is unsigned" in claims["cisco-cucm-cdr-15-cmr-fields"]["claim"]
    assert "numberPacketsLost may be negative" in claims["cisco-cucm-cdr-15-cmr-fields"]["claim"]
    assert claims["cisco-cucm-cdr-15-cmr-fields"]["source_date"] == "2026-04-09"
    assert claims["cisco-cucm-cdr-15-export-cdr-type-mapping"]["source_date"] == "2026-04-09"
    assert "callingPartyNumber and finalCalledPartyNumber to VARCHAR(50)" in claims[
        "cisco-cucm-cdr-15-export-cdr-type-mapping"
    ]["claim"]
    assert claims["cisco-cucm-cdr-15-export-cmr-type-mapping"]["source_date"] == "2026-04-09"
    assert claims["cisco-cucm-cdr-15-export-cmr-type-mapping"]["url"].endswith(
        "cucm_b_reporting-and-billing-administration-guide_chapter_01100.html"
    )
    assert "globalCallID_callId to INTEGER and directoryNum to VARCHAR(50)" in claims[
        "cisco-cucm-cdr-15-export-cmr-type-mapping"
    ]["claim"]
    assert "VARCHAR" not in claims["cisco-cucm-cdr-15-cdr-fields"]["claim"]
    assert "VARCHAR" not in claims["cisco-cucm-cdr-15-cmr-fields"]["claim"]
    assert claims["splunk-fields-command-10-5-2605"]["url"] == (
        "https://help.splunk.com/en/splunk-cloud-platform/search/search-reference/"
        "10.5.2605/search-commands/fields"
    )
    assert "cisco-cmm-3-1-historical" not in claims
    assert {
        "cisco-roomos-26-2-api",
        "cisco-webex-xapi",
        "cisco-roomos-environmental-sensors",
        "cisco-roomos-people-presence",
        "cisco-roomos-thousandeyes-handoff",
        "cisco-broadworks-primary-interface",
    } <= set(claims)


def test_documented_recovery_contract_matches_path_bound_marker_behavior() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_DIR / "reference.md").read_text(encoding="utf-8")
    assert "backup marker stays\nbound to the original target path" in skill
    assert "reviewed rename-back operation" in reference
    assert "not a valid bundle at the backup location" in reference
    assert "validate.sh --output-dir <original-target>" in reference


def test_setup_rejects_validate_plus_dry_run_before_render_and_emits_no_json_prefix() -> None:
    with private_workspace() as root:
        out = root / "bundle"
        result = run_command(
            "bash",
            str(SETUP_PATH),
            "--spec",
            str(TEMPLATE_PATH),
            "--output-dir",
            str(out),
            "--validate",
            "--dry-run",
            "--json",
        )
        assert result.returncode == 2
        assert result.stdout == ""
        assert not out.exists()


def test_no_python_cache_artifacts_are_part_of_skill_contract() -> None:
    assert list(SKILL_DIR.rglob("*.pyc")) == []
    assert list(SKILL_DIR.rglob("__pycache__")) == []

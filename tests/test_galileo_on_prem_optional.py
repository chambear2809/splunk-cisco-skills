"""Security regressions for the optional Galileo On-Prem child skills."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import sys
import tarfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "skills"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_pair(prefix: str, directory: Path):
    previous = sys.modules.pop("render_bundle", None)
    try:
        renderer = load_module("render_bundle", directory / "render_bundle.py")
        lifecycle = load_module(f"{prefix}_lifecycle", directory / "lifecycle.py")
    finally:
        sys.modules.pop("render_bundle", None)
        if previous is not None:
            sys.modules["render_bundle"] = previous
    return renderer, lifecycle


AC_RENDER, AC_LIFECYCLE = load_pair(
    "optional_ac", SKILLS / "galileo-on-prem-agent-control-setup/scripts"
)
LUNA_RENDER, LUNA_LIFECYCLE = load_pair(
    "optional_luna", SKILLS / "galileo-on-prem-luna-studio-setup/scripts"
)
AIR_GAP = load_module(
    "optional_air_gap",
    SKILLS / "galileo-on-prem-air-gap-setup/scripts/supply_chain.py",
)
STACK_CONTRACT = load_module(
    "optional_stack_contract",
    SKILLS / "galileo-on-prem-stack-setup/scripts/stack_lifecycle.py",
)


def rejects(callable_) -> None:
    with pytest.raises(SystemExit):
        callable_()


def redacted_secret_contract(path: str = "/credentials/password") -> dict:
    return {
        "schema": "galileo-on-prem-redacted-secret-input-contract/v1",
        "path_policy": "safe-helm-values-paths/v1",
        "leaves": [
            {
                "path": path,
                "shape": "string",
                "influence": ["helm-template", "kubernetes-server-dry-run"],
            }
        ],
    }


def write_real_oci_archive(
    tmp_path: Path,
    *,
    config_platforms: list[dict],
    declared_platforms: list[dict | None],
    nested: bool,
    duplicate_descriptor: bool = False,
    manifest_document_media: str = "application/vnd.oci.image.manifest.v1+json",
    manifest_descriptor_media: str = "application/vnd.oci.image.manifest.v1+json",
    config_media: str = "application/vnd.oci.image.config.v1+json",
    layer_media: str = "application/vnd.oci.image.layer.v1.tar",
    manifest_size_delta: int = 0,
    config_size_delta: int = 0,
    config_digest_override: str | None = None,
    duplicate_config_key: bool = False,
    extra_blob: bool = False,
) -> tuple[Path, str]:
    """Build a real closed OCI tar without mocking the verifier."""
    assert len(config_platforms) == len(declared_platforms)

    def encoded(value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    blobs: dict[str, bytes] = {}
    manifest_descriptors: list[dict] = []
    for index, (config_platform, declared_platform) in enumerate(
        zip(config_platforms, declared_platforms, strict=True)
    ):
        layer = f"fixture-layer-{index}".encode()
        layer_hash = hashlib.sha256(layer).hexdigest()
        blobs[layer_hash] = layer
        config_document = {
            **config_platform,
            "config": {"Labels": {"fixture.index": str(index)}},
            "rootfs": {"type": "layers", "diff_ids": [f"sha256:{layer_hash}"]},
        }
        if duplicate_config_key:
            config = (
                '{"architecture":"amd64","architecture":"arm64",'
                f'"config":{{}},"os":"linux","rootfs":{{"diff_ids":'
                f'["sha256:{layer_hash}"],"type":"layers"}}}}'
            ).encode()
        else:
            config = encoded(config_document)
        config_hash = hashlib.sha256(config).hexdigest()
        blobs[config_hash] = config
        manifest = encoded(
            {
                "schemaVersion": 2,
                "mediaType": manifest_document_media,
                "config": {
                    "mediaType": config_media,
                    "digest": (
                        config_digest_override
                        if index == 0 and config_digest_override is not None
                        else f"sha256:{config_hash}"
                    ),
                    "size": len(config) + (config_size_delta if index == 0 else 0),
                },
                "layers": [
                    {
                        "mediaType": layer_media,
                        "digest": f"sha256:{layer_hash}",
                        "size": len(layer),
                    }
                ],
            }
        )
        manifest_hash = hashlib.sha256(manifest).hexdigest()
        blobs[manifest_hash] = manifest
        descriptor = {
            "mediaType": manifest_descriptor_media,
            "digest": f"sha256:{manifest_hash}",
            "size": len(manifest) + (manifest_size_delta if index == 0 else 0),
        }
        if declared_platform is not None:
            descriptor["platform"] = declared_platform
        manifest_descriptors.append(descriptor)
    if duplicate_descriptor:
        manifest_descriptors.append(json.loads(json.dumps(manifest_descriptors[0])))
    if nested:
        nested_index = encoded(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": manifest_descriptors,
            }
        )
        nested_hash = hashlib.sha256(nested_index).hexdigest()
        blobs[nested_hash] = nested_index
        root_descriptor = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "digest": f"sha256:{nested_hash}",
            "size": len(nested_index),
        }
    else:
        assert len(manifest_descriptors) == 1
        root_descriptor = manifest_descriptors[0]
    root_digest = root_descriptor["digest"]
    root_index = encoded(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [root_descriptor],
        }
    )
    layout = encoded({"imageLayoutVersion": "1.0.0"})
    if extra_blob:
        payload = b"unreferenced"
        blobs[hashlib.sha256(payload).hexdigest()] = payload
    archive_path = tmp_path / "fixture.oci.tar"
    with tarfile.open(archive_path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in (
            ("oci-layout", layout),
            ("index.json", root_index),
            *((f"blobs/sha256/{digest}", payload) for digest, payload in blobs.items()),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            member.mode = 0o600
            archive.addfile(member, io.BytesIO(payload))
    archive_path.chmod(0o600)
    return archive_path, root_digest


@pytest.mark.parametrize(
    "scanner",
    (AC_RENDER.scan_nonsecret, LUNA_RENDER.scan),
)
@pytest.mark.parametrize(
    "payload",
    (
        {"metadata": {"owner": "password=fixture-only"}},
        {"notes": "Bearer fixture-token"},
        {"kind": "Secret", "stringData": {"arbitrary": "fixture"}},
        {"galileo_secrets": {"arbitrary": "fixture"}},
    ),
)
def test_nonsecret_scanners_reject_generic_credential_material(
    scanner, payload
) -> None:
    rejects(lambda: scanner(payload))


@pytest.mark.parametrize(
    "scanner",
    (AC_RENDER.scan_nonsecret, LUNA_RENDER.scan),
)
def test_nonsecret_scanners_allow_exact_secret_reference_names(scanner) -> None:
    scanner(
        {
            "secretName": "reviewed-secret",
            "existingSecret": "reviewed-secret",
            "imagePullSecret": "reviewed-pull-secret",
        }
    )


def test_minimal_tool_environments_do_not_repurpose_home(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("{}\n", encoding="utf-8")
    kubeconfig.chmod(0o600)
    for lifecycle in (AC_LIFECYCLE, LUNA_LIFECYCLE):
        holder = lifecycle.prepare_runtime(str(kubeconfig))
        try:
            assert "HOME" not in lifecycle.command_env()
        finally:
            holder.cleanup()
    auth = tmp_path / "auth.json"
    auth.write_text('{"auths": {}}\n', encoding="utf-8")
    auth.chmod(0o600)
    env, holder = AIR_GAP.minimal_env(auth)
    try:
        assert "HOME" not in env
    finally:
        holder.cleanup()


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
@pytest.mark.parametrize("auth_key", ("exec", "auth-provider"))
def test_child_lifecycles_reject_external_kubeconfig_auth(
    lifecycle, auth_key: str
) -> None:
    rejects(lambda: lifecycle.validate_kubeconfig_user_auth({auth_key: {}}))


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_umbrella_owned_child_rejects_standalone_release(lifecycle) -> None:
    metadata = {"ownership": "umbrella-overlay"}
    lifecycle.validate_observed_release_ownership(None, metadata)
    rejects(
        lambda: lifecycle.validate_observed_release_ownership(
            {"name": "conflicting-release"}, metadata
        )
    )


def test_luna_gpu_count_rejects_booleans() -> None:
    assert LUNA_RENDER.integer_gpu_count(0) == 0
    assert LUNA_RENDER.integer_gpu_count(1) == 1
    rejects(lambda: LUNA_RENDER.integer_gpu_count(False))
    rejects(lambda: LUNA_RENDER.integer_gpu_count(True))


@pytest.mark.parametrize(
    "reader",
    (AC_RENDER.secure_read, LUNA_RENDER.secure_read, AIR_GAP.secure_read),
)
def test_secure_inputs_reject_symlink_hardlink_fifo_and_symlink_ancestor(
    tmp_path: Path, reader
) -> None:
    source = tmp_path / "source"
    source.write_text("fixture\n", encoding="utf-8")
    source.chmod(0o600)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(source)
    rejects(lambda: reader(symlink, "fixture"))

    hardlink = tmp_path / "hardlink"
    os.link(source, hardlink)
    rejects(lambda: reader(source, "fixture"))

    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    rejects(lambda: reader(fifo, "fixture"))

    real_dir = tmp_path / "real"
    real_dir.mkdir(mode=0o700)
    nested = real_dir / "nested"
    nested.write_text("fixture\n", encoding="utf-8")
    nested.chmod(0o600)
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(real_dir, target_is_directory=True)
    rejects(lambda: reader(linked_dir / "nested", "fixture"))


def test_canonical_derived_outputs_change_with_security_semantics() -> None:
    ac = {
        "deployment": {
            "ownership": "standalone",
            "release_name": "agent-control",
            "namespace": "galileo",
        },
        "database": {"name": "agent_control", "bootstrap": False},
        "routing": {"mode": "none", "external_url": ""},
        "feature_flag": {"source": "central"},
        "secret_contract": {},
    }
    first = AC_RENDER.canonical_overlay(ac)
    changed = json.loads(json.dumps(ac))
    changed["feature_flag"]["source"] = "helm-env"
    assert first != AC_RENDER.canonical_overlay(changed)
    ac_lifecycle = AC_RENDER.canonical_lifecycle(ac)
    assert "apply-uninstall" not in ac_lifecycle["phases"]
    assert ac_lifecycle["mutation_execution"] == (
        "galileo-cse-joint-session-handoff-only"
    )
    assert ac_lifecycle["blocked_apply_modes"] == [
        "apply-install",
        "apply-upgrade",
        "apply-rollback",
        "apply-uninstall",
    ]

    luna = {
        "deployment": {
            "ownership": "standalone",
            "release_name": "luna-studio",
            "namespace": "galileo",
        },
        "secret_contracts": {
            "jwt": {"name": "jwt"},
            "admin": {"name": "admin"},
            "database": {"name": "database"},
            "nextauth": {"name": "nextauth"},
            "galileo_api": None,
            "object_auth": None,
            "remote": None,
        },
        "object_store": {"provider": "aws", "auth_mode": "irsa", "bucket": "one"},
        "routing": {
            "mode": "customer",
            "public_url": "https://luna.internal.example/",
            "tls_secret_name": "luna-tls",
            "ingress_class": "",
        },
        "training": {
            "provider": "kubernetes",
            "remote": None,
            "gpu": {
                "enabled": False,
                "count": 0,
                "resource": "nvidia.com/gpu",
                "node_selector": {},
                "tolerations": [],
            },
            "vertex_ai": None,
        },
        "resilience": {"hpa": False, "pdb": False, "network_policy": False},
    }
    first_luna = LUNA_RENDER.canonical_overlay(luna)
    changed_luna = json.loads(json.dumps(luna))
    changed_luna["object_store"]["bucket"] = "two"
    assert first_luna != LUNA_RENDER.canonical_overlay(changed_luna)
    assert LUNA_RENDER.canonical_lifecycle(luna)["mutation_execution"] == (
        "galileo-cse-joint-session-handoff-only"
    )


def test_upgrade_comparator_is_stable_only_and_rejects_downgrade() -> None:
    assert AC_LIFECYCLE.semver("1.2.4") > AC_LIFECYCLE.semver("1.2.3")
    assert LUNA_LIFECYCLE.semver("2.2.0") > LUNA_LIFECYCLE.semver("2.1.5")
    assert not (AC_LIFECYCLE.semver("1.2.2") > AC_LIFECYCLE.semver("1.2.3"))
    rejects(lambda: AC_LIFECYCLE.semver("1.2.4-rc.1"))
    rejects(lambda: LUNA_LIFECYCLE.semver("2.2.0+build"))


def test_automated_optional_component_uninstall_is_fail_closed() -> None:
    rejects(lambda: AC_LIFECYCLE.uninstall(None, {}))
    rejects(lambda: LUNA_LIFECYCLE.uninstall(None, {}))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda: AC_LIFECYCLE.apply_release(
            None, {}, Path("/never-read"), "apply-install"
        ),
        lambda: LUNA_LIFECYCLE.apply(None, {}, Path("/never-read"), "apply-upgrade"),
        lambda: AIR_GAP.push(None, Path("/never-read"), {}),
    ),
)
def test_all_optional_external_mutations_are_handoff_only(mutation) -> None:
    rejects(mutation)


@pytest.mark.parametrize(
    ("lifecycle", "flag", "accept_flag", "extra"),
    (
        (
            AC_LIFECYCLE,
            "--apply-install",
            "--accept-agent-control-install",
            [],
        ),
        (
            AC_LIFECYCLE,
            "--apply-upgrade",
            "--accept-agent-control-upgrade",
            [],
        ),
        (
            AC_LIFECYCLE,
            "--apply-rollback",
            "--accept-agent-control-rollback",
            ["--previous-bundle", "/never-read-previous"],
        ),
        (
            AC_LIFECYCLE,
            "--apply-uninstall",
            "--accept-agent-control-uninstall",
            [
                "--retention-file",
                "/never-read-retention",
                "--confirm-target",
                "galileo/agent-control",
            ],
        ),
        (
            LUNA_LIFECYCLE,
            "--apply-install",
            "--accept-luna-studio-install",
            [],
        ),
        (
            LUNA_LIFECYCLE,
            "--apply-upgrade",
            "--accept-luna-studio-upgrade",
            [],
        ),
        (
            LUNA_LIFECYCLE,
            "--apply-rollback",
            "--accept-luna-studio-rollback",
            ["--previous-bundle", "/never-read-previous"],
        ),
        (
            LUNA_LIFECYCLE,
            "--apply-uninstall",
            "--accept-luna-studio-uninstall",
            [
                "--retention-file",
                "/never-read-retention",
                "--confirm-target",
                "galileo/luna-studio",
            ],
        ),
    ),
)
def test_child_apply_cli_fails_before_kubeconfig_or_bundle_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle,
    flag: str,
    accept_flag: str,
    extra: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "prepare_runtime",
        lambda *_: pytest.fail("mutation sentinel touched kubeconfig state"),
    )
    monkeypatch.setattr(
        lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("mutation sentinel ran a subprocess"),
    )
    monkeypatch.setattr(
        lifecycle,
        "new_private_json" if lifecycle is AC_LIFECYCLE else "write_new",
        lambda *_: pytest.fail("mutation sentinel wrote a file"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lifecycle.py",
            flag,
            "--bundle",
            "/never-read",
            "--kube-context",
            "never-contact",
            "--kubeconfig",
            "/never-read",
            "--galileo-console-url",
            "https://galileo.internal.example/",
            "--evidence-file",
            "/never-write-evidence",
            "--secret-values-file",
            "/never-read-secret-values",
            "--approval-file",
            "/never-read-approval",
            accept_flag,
            *extra,
        ],
    )
    rejects(lifecycle.main)


def test_registry_push_cli_fails_before_bundle_or_auth_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        AIR_GAP,
        "verify_bundle",
        lambda *_: pytest.fail("registry mutation sentinel touched the bundle"),
    )
    monkeypatch.setattr(
        AIR_GAP,
        "write_json",
        lambda *_: pytest.fail("registry mutation sentinel wrote a file"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "supply_chain.py",
            "--push-registry",
            "--bundle",
            "/never-read",
            "--galileo-console-url",
            "https://galileo.internal.example/",
            "--registry-auth-file",
            "/never-read-auth",
            "--approval-file",
            "/never-read-approval",
            "--result-file",
            "/never-write-result",
            "--accept-registry-write",
        ],
    )
    rejects(AIR_GAP.main)
    source = (
        SKILLS / "galileo-on-prem-air-gap-setup/scripts/supply_chain.py"
    ).read_text(encoding="utf-8")
    assert '"skopeo"' not in source
    assert '"status": "pushed-and-verified"' not in source


def test_air_gap_exposes_unvalidated_producer_contracts() -> None:
    assert AIR_GAP.completion_gates([]) == ["endpoint_rewrite_evidence_missing"]
    assert AIR_GAP.completion_gates([{"name": "model"}]) == [
        "endpoint_rewrite_evidence_missing",
        "stack_model_evidence_missing",
    ]


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_redacted_secret_contract_and_render_hash_are_not_offline_verifiers(
    lifecycle,
) -> None:
    low_entropy = b'auth:\n  password: "1234"\n  enabled: true\n'
    candidate = b'auth:\n  password: "9999"\n  enabled: true\n'
    changed_shape = b'auth:\n  password: "1234"\n  enabled: "true"\n'
    contract = lifecycle.redacted_secret_input_contract(low_entropy)
    assert contract == lifecycle.redacted_secret_input_contract(candidate)
    assert contract != lifecycle.redacted_secret_input_contract(changed_shape)
    serialized = json.dumps(contract, sort_keys=True)
    for forbidden in ("1234", "9999", hashlib.sha256(low_entropy).hexdigest()):
        assert forbidden not in serialized

    def documents(secret: str) -> list[dict]:
        return [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "fixture"},
                "stringData": {"password": secret},
            },
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "fixture"},
                "spec": {"replicas": 1},
            },
        ]

    first = lifecycle.redacted_render_sha256(documents("1234"))
    assert first == lifecycle.redacted_render_sha256(documents("9999"))
    structurally_changed = documents("9999")
    structurally_changed[-1]["spec"]["selector"] = {}
    assert first != lifecycle.redacted_render_sha256(structurally_changed)
    persisted = json.dumps(
        {
            "inputs": {"secret_input_contract": contract},
            "redacted_render_sha256": first,
        },
        sort_keys=True,
    )
    assert "1234" not in persisted
    assert hashlib.sha256(low_entropy).hexdigest() not in persisted
    source = Path(lifecycle.__file__).read_text(encoding="utf-8")
    for forbidden_field in (
        "secret_values_sha256",
        "render_input_sha256",
        "helm_render_sha256",
    ):
        assert forbidden_field not in source


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_action_approval_binds_fresh_exact_preflight(lifecycle) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    evidence = {
        "created_at": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    }
    evidence_sha = "a" * 64
    approval = {
        "issued_at": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "preflight_sha256": evidence_sha,
    }
    lifecycle.require_approval_preflight_binding(approval, evidence, evidence_sha)
    wrong = dict(approval, preflight_sha256="b" * 64)
    rejects(
        lambda: lifecycle.require_approval_preflight_binding(
            wrong, evidence, evidence_sha
        )
    )
    stale = dict(
        approval,
        issued_at=(now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
    )
    rejects(
        lambda: lifecycle.require_approval_preflight_binding(
            stale, evidence, evidence_sha
        )
    )
    rejects(
        lambda: lifecycle.require_approval_preflight_binding(
            approval, evidence, "c" * 64
        )
    )


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_attestation_parser_requires_canonical_duplicate_free_json(
    tmp_path: Path, lifecycle
) -> None:
    duplicate = tmp_path / f"{lifecycle.__name__}-duplicate.json"
    duplicate.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
    duplicate.chmod(0o600)
    rejects(lambda: lifecycle.private_json(str(duplicate), "fixture attestation"))

    noncanonical = tmp_path / f"{lifecycle.__name__}-noncanonical.json"
    noncanonical.write_text('{"schema": "one"}\n', encoding="utf-8")
    noncanonical.chmod(0o600)
    rejects(lambda: lifecycle.private_json(str(noncanonical), "fixture attestation"))

    canonical = tmp_path / f"{lifecycle.__name__}-canonical.json"
    canonical.write_text(
        json.dumps({"schema": "one"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    canonical.chmod(0o600)
    assert lifecycle.private_json(str(canonical), "fixture attestation") == {
        "schema": "one"
    }


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_evidence_comparison_does_not_coerce_bool_and_int(lifecycle) -> None:
    assert lifecycle.exact_value({"passed": True}, {"passed": True})
    assert not lifecycle.exact_value({"passed": 1}, {"passed": True})
    assert not lifecycle.exact_value({"count": False}, {"count": 0})


def test_air_gap_unknown_public_dns_requires_explicit_internal_policy() -> None:
    assert AIR_GAP.public_endpoint("evil.example.net:443")
    assert not AIR_GAP.internal_hostname(
        "evil.example.net:443", {"registry.internal.example"}, {"internal.example"}
    )
    assert AIR_GAP.internal_hostname(
        "registry.internal.example:443",
        {"registry.internal.example"},
        {"internal.example"},
    )
    assert not AIR_GAP.internal_hostname(
        "registry.internal.example.evil.net",
        {"registry.internal.example"},
        {"internal.example"},
    )
    assert (
        AIR_GAP.registry(
            "registry.internal.example/galileo",
            {"registry.internal.example"},
            {"internal.example"},
        )
        == "registry.internal.example/galileo"
    )
    rejects(lambda: AIR_GAP.registry("10.0.0.20/galileo", set(), set()))
    rejects(
        lambda: AIR_GAP.registry(
            "registry.internal.example.evil.net/galileo",
            {"registry.internal.example"},
            {"internal.example"},
        )
    )


def test_air_gap_endpoint_closure_is_exact_and_rejects_public_hosts() -> None:
    exact_hosts = {"registry.internal.example", "db.internal.example"}
    suffixes = {"internal.example"}
    AIR_GAP.require_exact_endpoint_closure(
        {"registry.internal.example", "db.internal.example:5432"},
        {"db.internal.example:5432"},
        "registry.internal.example",
        exact_hosts,
        suffixes,
    )
    rejects(
        lambda: AIR_GAP.require_exact_endpoint_closure(
            {
                "registry.internal.example",
                "db.internal.example:5432",
                "unused.internal.example",
            },
            {"db.internal.example:5432"},
            "registry.internal.example",
            exact_hosts,
            suffixes,
        )
    )
    rejects(
        lambda: AIR_GAP.require_exact_endpoint_closure(
            {"registry.internal.example", "api.vendor.example:443"},
            {"api.vendor.example:443"},
            "registry.internal.example",
            exact_hosts,
            suffixes,
        )
    )


def test_air_gap_source_and_mirror_roles_never_collapse() -> None:
    destination = "registry.internal.example/galileo"
    AIR_GAP.validate_source_mirror_roles(
        "vendor.example/api:1.2.3",
        "registry.internal.example/galileo/api:1.2.3",
        destination,
        "fixture",
    )
    for source, mirror in (
        (
            "registry.internal.example/galileo/api:1.2.3",
            "registry.internal.example/galileo/api:1.2.3",
        ),
        (
            "registry.internal.example/vendor/api:1.2.3",
            "registry.internal.example/galileo/api:1.2.3",
        ),
        ("vendor.example/api:1.2.3", "other.internal.example/api:1.2.3"),
    ):
        rejects(
            lambda source=source, mirror=mirror: AIR_GAP.validate_source_mirror_roles(
                source, mirror, destination, "fixture"
            )
        )


def test_air_gap_manifest_parser_rejects_source_equal_to_mirror(tmp_path: Path) -> None:
    reference = "registry.internal.example/galileo/api:1.2.3"
    digest = "sha256:" + "a" * 64
    document = {
        "schema": "galileo-air-gap-image-manifest/v1",
        "release": "fixture-1.2.3",
        "images": [
            {
                "source": reference,
                "source_digest": digest,
                "mirror": reference,
                "mirror_digest": digest,
                "archive": "/unreached/archive",
                "archive_sha256": "b" * 64,
                "architectures": ["amd64"],
                "uses": ["runtime"],
                "scan_attestation_file": "/unreached/scan",
                "scan_attestation_sha256": "c" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)
    rejects(
        lambda: AIR_GAP.parse_inventory(
            AIR_GAP.secure_read(path, "manifest"),
            "fixture-1.2.3",
            {"amd64"},
            "registry.internal.example/galileo",
        )
    )


def test_air_gap_strict_attestation_json_rejects_duplicates_and_noncanonical_form(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"one","schema":"two"}\n', encoding="utf-8")
    duplicate.chmod(0o600)
    artifact = AIR_GAP.secure_read(duplicate, "duplicate attestation", private=True)
    rejects(
        lambda: AIR_GAP.strict_json_mapping(
            artifact, "duplicate attestation", canonical=True
        )
    )

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text('{"schema": "one"}\n', encoding="utf-8")
    noncanonical.chmod(0o600)
    artifact = AIR_GAP.secure_read(
        noncanonical, "noncanonical attestation", private=True
    )
    rejects(
        lambda: AIR_GAP.strict_json_mapping(
            artifact, "noncanonical attestation", canonical=True
        )
    )


def test_air_gap_oci_identity_accepts_valid_single_and_multi_archives(
    tmp_path: Path,
) -> None:
    single_path, single_digest = write_real_oci_archive(
        tmp_path,
        config_platforms=[{"os": "linux", "architecture": "amd64"}],
        declared_platforms=[None],
        nested=False,
    )
    single = AIR_GAP.oci_identity(AIR_GAP.secure_read(single_path, "single OCI"))
    assert single["root_digest"] == single_digest
    assert single["architectures"] == ["amd64"]
    assert len(single["manifest_digests"]) == 1

    multi_root = tmp_path / "multi"
    multi_root.mkdir()
    multi_path, multi_digest = write_real_oci_archive(
        multi_root,
        config_platforms=[
            {"os": "linux", "architecture": "amd64", "variant": "v3"},
            {"os": "linux", "architecture": "arm64", "variant": "v8"},
        ],
        declared_platforms=[
            {"os": "linux", "architecture": "amd64", "variant": "v3"},
            {"os": "linux", "architecture": "arm64", "variant": "v8"},
        ],
        nested=True,
    )
    multi = AIR_GAP.oci_identity(AIR_GAP.secure_read(multi_path, "multi OCI"))
    assert multi["root_digest"] == multi_digest
    assert multi["architectures"] == ["amd64", "arm64"]
    assert len(multi["manifest_digests"]) == 2


def test_air_gap_inventory_consumes_real_oci_platform_evidence(
    tmp_path: Path,
) -> None:
    archive, digest = write_real_oci_archive(
        tmp_path,
        config_platforms=[{"os": "linux", "architecture": "amd64"}],
        declared_platforms=[{"os": "linux", "architecture": "amd64"}],
        nested=True,
    )
    source = "vendor.example/api:1.2.3"
    mirror = "registry.internal.example/galileo/api:1.2.3"
    scanned_at = (
        (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    scan = {
        "schema": "galileo-image-scan-attestation/v1",
        "subject": source,
        "image_digest": digest,
        "passed": True,
        "scanner": "fixture-scanner",
        "scanner_version": "1.0.0",
        "scanned_at": scanned_at,
        "policy": "reviewed fixture policy",
    }
    scan_path = tmp_path / "real-oci-scan.json"
    scan_raw = (json.dumps(scan, indent=2, sort_keys=True) + "\n").encode()
    scan_path.write_bytes(scan_raw)
    scan_path.chmod(0o600)
    manifest = {
        "schema": "galileo-air-gap-image-manifest/v1",
        "release": "fixture-1.2.3",
        "images": [
            {
                "source": source,
                "source_digest": digest,
                "mirror": mirror,
                "mirror_digest": digest,
                "archive": str(archive),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "architectures": ["amd64"],
                "uses": ["runtime"],
                "scan_attestation_file": str(scan_path),
                "scan_attestation_sha256": hashlib.sha256(scan_raw).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "real-oci-manifest.json"
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    manifest_path.chmod(0o600)
    _document, normalized = AIR_GAP.parse_inventory(
        AIR_GAP.secure_read(manifest_path, "real OCI manifest"),
        "fixture-1.2.3",
        {"amd64"},
        "registry.internal.example/galileo",
    )
    assert normalized[0]["source_digest"] == digest
    assert normalized[0]["architectures"] == ["amd64"]


@pytest.mark.parametrize(
    "case",
    (
        "architecture-mismatch",
        "variant-mismatch",
        "missing-index-platform",
        "missing-config-os",
        "missing-config-architecture",
        "missing-descriptor-os",
        "missing-descriptor-architecture",
        "unknown-os",
        "unknown-config-architecture",
        "invalid-variant",
        "unknown-platform-field",
        "duplicate-descriptor",
        "duplicate-platform",
        "manifest-media-mismatch",
        "manifest-size-mismatch",
        "config-media-mismatch",
        "config-size-mismatch",
        "config-digest-missing",
        "layer-media-unknown",
        "duplicate-config-key",
        "unreferenced-blob",
    ),
)
def test_air_gap_oci_identity_rejects_cross_layer_and_closure_forgery(
    tmp_path: Path, case: str
) -> None:
    config_platforms = [{"os": "linux", "architecture": "amd64"}]
    declared_platforms: list[dict | None] = [{"os": "linux", "architecture": "amd64"}]
    options: dict[str, object] = {"nested": True}
    if case == "architecture-mismatch":
        declared_platforms[0] = {"os": "linux", "architecture": "arm64"}
    elif case == "variant-mismatch":
        config_platforms[0]["variant"] = "v3"
        declared_platforms[0]["variant"] = "v2"
    elif case == "missing-index-platform":
        declared_platforms[0] = None
    elif case == "missing-config-os":
        config_platforms[0].pop("os")
    elif case == "missing-config-architecture":
        config_platforms[0].pop("architecture")
    elif case == "missing-descriptor-os":
        declared_platforms[0].pop("os")
    elif case == "missing-descriptor-architecture":
        declared_platforms[0].pop("architecture")
    elif case == "unknown-os":
        config_platforms[0]["os"] = "darwin"
        declared_platforms[0]["os"] = "darwin"
    elif case == "unknown-config-architecture":
        config_platforms[0]["architecture"] = "mips64"
        declared_platforms[0]["architecture"] = "mips64"
    elif case == "invalid-variant":
        config_platforms[0]["variant"] = "8"
        declared_platforms[0]["variant"] = "8"
    elif case == "unknown-platform-field":
        declared_platforms[0]["os.version"] = "fixture"
    elif case == "duplicate-descriptor":
        options["duplicate_descriptor"] = True
    elif case == "duplicate-platform":
        config_platforms.append({"os": "linux", "architecture": "amd64"})
        declared_platforms.append({"os": "linux", "architecture": "amd64"})
    elif case == "manifest-media-mismatch":
        options["manifest_document_media"] = (
            "application/vnd.docker.distribution.manifest.v2+json"
        )
    elif case == "manifest-size-mismatch":
        options["manifest_size_delta"] = 1
    elif case == "config-media-mismatch":
        options["config_media"] = "application/vnd.docker.container.image.v1+json"
    elif case == "config-size-mismatch":
        options["config_size_delta"] = 1
    elif case == "config-digest-missing":
        options["config_digest_override"] = "sha256:" + "f" * 64
    elif case == "layer-media-unknown":
        options["layer_media"] = "application/octet-stream"
    elif case == "duplicate-config-key":
        options["duplicate_config_key"] = True
    elif case == "unreferenced-blob":
        options["extra_blob"] = True
    else:  # pragma: no cover - parameter list and branch table are one contract
        raise AssertionError(case)
    archive, _digest = write_real_oci_archive(
        tmp_path,
        config_platforms=config_platforms,
        declared_platforms=declared_platforms,
        **options,
    )
    rejects(
        lambda: AIR_GAP.oci_identity(AIR_GAP.secure_read(archive, f"forged OCI {case}"))
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda scan, source, digest: scan.pop("subject"),
        lambda scan, source, digest: scan.update(subject="wrong.example/api:1.2.3"),
        lambda scan, source, digest: scan.update(image_digest="sha256:" + "b" * 64),
        lambda scan, source, digest: scan.update(passed=1),
        lambda scan, source, digest: scan.update(extra="forbidden"),
    ),
)
def test_air_gap_rejects_malformed_or_wrong_subject_scan_attestations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation
) -> None:
    source = "vendor.example/api:1.2.3"
    mirror = "registry.internal.example/galileo/api:1.2.3"
    digest = "sha256:" + "a" * 64
    archive = tmp_path / "image.oci.tar"
    archive.write_bytes(b"fixture OCI archive")
    archive.chmod(0o600)
    scan = {
        "schema": "galileo-image-scan-attestation/v1",
        "subject": source,
        "image_digest": digest,
        "passed": True,
        "scanner": "fixture-scanner",
        "scanner_version": "1.0.0",
        "scanned_at": (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "policy": "reviewed fixture policy",
    }
    mutation(scan, source, digest)
    scan_path = tmp_path / "scan.json"
    scan_raw = (json.dumps(scan, indent=2, sort_keys=True) + "\n").encode()
    scan_path.write_bytes(scan_raw)
    scan_path.chmod(0o600)
    manifest = {
        "schema": "galileo-air-gap-image-manifest/v1",
        "release": "fixture-1.2.3",
        "images": [
            {
                "source": source,
                "source_digest": digest,
                "mirror": mirror,
                "mirror_digest": digest,
                "archive": str(archive),
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "architectures": ["amd64"],
                "uses": ["runtime"],
                "scan_attestation_file": str(scan_path),
                "scan_attestation_sha256": hashlib.sha256(scan_raw).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    )
    manifest_path.chmod(0o600)
    monkeypatch.setattr(
        AIR_GAP,
        "oci_identity",
        lambda _: {"root_digest": digest, "architectures": ["amd64"]},
    )
    rejects(
        lambda: AIR_GAP.parse_inventory(
            AIR_GAP.secure_read(manifest_path, "manifest"),
            "fixture-1.2.3",
            {"amd64"},
            "registry.internal.example/galileo",
        )
    )


def test_air_gap_stack_image_evidence_is_mandatory_and_private(tmp_path: Path) -> None:
    evidence = tmp_path / "rendered-image-inventory-evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    evidence.chmod(0o644)
    rejects(
        lambda: AIR_GAP.verified_stack_evidence(
            str(tmp_path / "missing-stack"),
            "a" * 64,
            str(evidence),
            "b" * 64,
        )
    )


def test_air_gap_consumes_exact_stack_rendered_image_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stack"
    root.mkdir(mode=0o700)
    bundle_sha = "a" * 64
    chart_sha = "b" * 64
    image_sha = "c" * 64
    manifest = {"bundle_sha256": bundle_sha}
    stack_spec = {
        "stack": {"chart_version": "1.2.3", "chart_sha256": chart_sha},
        "galileoctl": {"enabled": False},
        "target": {
            "kube_context": "fixture",
            "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "d" * 64,
            "cluster_uid": "cluster-uid",
            "namespace": "galileo",
        },
    }
    monkeypatch.setitem(
        sys.modules,
        "stack_lifecycle",
        types.SimpleNamespace(verify_bundle=lambda _: (manifest, stack_spec)),
    )
    evidence = {
        "schema": "galileo-on-prem-stack-rendered-image-inventory/v1",
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": bundle_sha,
        "charts": [
            {
                "name": "galileo-stack",
                "release": "galileo-stack",
                "version": "1.2.3",
                "sha256": chart_sha,
            }
        ],
        "inputs": {
            "stack_nonsecret_values_sha256": "e" * 64,
            "stack_secret_contract_sha256": "f" * 64,
            "galileoctl_nonsecret_values_sha256": "",
            "galileoctl_secret_contract_sha256": "",
        },
        "redacted_render_sha256": "1" * 64,
        "target": {
            "context": "fixture",
            "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "d" * 64,
            "kube_system_uid": "cluster-uid",
            "namespace": "galileo",
            "namespace_uid": "namespace-uid",
        },
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "items": [
            {
                "release": "galileo-stack",
                "source_object": "Deployment/api",
                "container_type": "container",
                "container": "api",
                "image": f"registry.vendor.example/api:1.2.3@sha256:{image_sha}",
                "digest": f"sha256:{image_sha}",
                "eligible_architectures": ["amd64"],
            }
        ],
    }
    evidence_path = tmp_path / "rendered-images.json"
    raw = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    evidence_path.write_bytes(raw)
    evidence_path.chmod(0o600)
    result = AIR_GAP.verified_stack_evidence(
        str(root), bundle_sha, str(evidence_path), hashlib.sha256(raw).hexdigest()
    )
    assert result[0] == bundle_sha
    assert result[1] == [
        {"name": "galileo-stack", "version": "1.2.3", "sha256": chart_sha}
    ]
    assert result[2] == {"registry.vendor.example/api:1.2.3"}

    empty = dict(evidence)
    empty["items"] = []
    empty_path = tmp_path / "empty-rendered-images.json"
    empty_raw = (json.dumps(empty, indent=2, sort_keys=True) + "\n").encode()
    empty_path.write_bytes(empty_raw)
    empty_path.chmod(0o600)
    rejects(
        lambda: AIR_GAP.verified_stack_evidence(
            str(root),
            bundle_sha,
            str(empty_path),
            hashlib.sha256(empty_raw).hexdigest(),
        )
    )
    wrong_type = json.loads(json.dumps(evidence))
    wrong_type["inputs"]["stack_secret_contract_sha256"] = int("7" * 64)
    wrong_type_path = tmp_path / "wrong-type-rendered-images.json"
    wrong_type_raw = (json.dumps(wrong_type, indent=2, sort_keys=True) + "\n").encode()
    wrong_type_path.write_bytes(wrong_type_raw)
    wrong_type_path.chmod(0o600)
    rejects(
        lambda: AIR_GAP.verified_stack_evidence(
            str(root),
            bundle_sha,
            str(wrong_type_path),
            hashlib.sha256(wrong_type_raw).hexdigest(),
        )
    )


def test_air_gap_rejects_empty_and_forged_stack_image_rows() -> None:
    assert AIR_GAP.OCI_DIGEST.fullmatch("sha256:" + "a" * 64)
    assert not AIR_GAP.OCI_DIGEST.fullmatch("")
    rejects(
        lambda: AIR_GAP.image_reference("registry/image@sha256:" + "a" * 64, "image")
    )
    rejects(lambda: AIR_GAP.image_reference("registry/image:latest", "image"))


def test_air_gap_architecture_coverage_is_bound_per_rendered_workload() -> None:
    digest = "sha256:" + "a" * 64
    mirror = "registry.internal.example/galileo/api:1.2.3"
    document = {
        "items": [
            {
                "release": "galileo-stack",
                "source_object": "Deployment/api",
                "container_type": "container",
                "container": "api",
                "image": f"{mirror}@{digest}",
                "digest": digest,
                "eligible_architectures": ["amd64", "arm64"],
            }
        ]
    }
    image = {
        "mirror": mirror,
        "architectures": ["amd64", "arm64"],
    }
    AIR_GAP.require_image_architecture_coverage([document], [image], {"amd64", "arm64"})
    image["architectures"] = ["amd64"]
    rejects(
        lambda: AIR_GAP.require_image_architecture_coverage(
            [document], [image], {"amd64", "arm64"}
        )
    )
    document["items"][0]["eligible_architectures"] = ["amd64"]
    AIR_GAP.require_image_architecture_coverage([document], [image], {"amd64", "arm64"})


def test_stack_and_air_gap_share_exact_architecture_bound_image_contract() -> None:
    """Replay one closed-schema seed through both producer and consumer validators."""
    digest = "sha256:" + "a" * 64
    source = "vendor.example/api:1.2.3"
    mirror = "registry.internal.example/galileo/api:1.2.3"
    chart = {
        "name": "galileo-stack",
        "release": "galileo",
        "version": "1.2.3",
        "sha256": "b" * 64,
    }
    target = {
        "context": "fixture",
        "api_server": "https://127.0.0.1:6443",
        "ca_sha256": "c" * 64,
        "kube_system_uid": "cluster-uid",
        "namespace": "galileo",
        "namespace_uid": "namespace-uid",
    }
    inputs = {
        "stack_nonsecret_values_sha256": "d" * 64,
        "stack_secret_contract_sha256": "e" * 64,
        "galileoctl_nonsecret_values_sha256": "",
        "galileoctl_secret_contract_sha256": "",
    }
    row = {
        "release": "galileo",
        "source_object": "Deployment/api",
        "container_type": "container",
        "container": "api",
        "image": f"{mirror}@{digest}",
        "digest": digest,
        "eligible_architectures": ["amd64"],
    }
    seed = {
        "evidence_sha256": "f" * 64,
        "source_bundle_sha256": "1" * 64,
        "charts": [chart],
        "inputs": inputs,
        "redacted_render_sha256": "2" * 64,
        "target": target,
        "items": [row],
    }
    image = {
        "source": source,
        "source_digest": digest,
        "mirror": mirror,
        "mirror_digest": digest,
        "archive_file": "images/api.oci.tar",
        "archive_sha256": "3" * 64,
        "architectures": ["amd64"],
        "uses": ["runtime"],
        "scan_attestation_file": "scans/api.json",
        "source_scan_attestation_sha256": "4" * 64,
        "scan_attestation_sha256": "5" * 64,
    }
    contract = {
        "schema": "galileo-on-prem-air-gap-bundle/v1",
        "bundle_sha256": "6" * 64,
        "charts": [
            {
                "name": "galileo-stack",
                "version": "1.2.3",
                "sha256": "b" * 64,
            }
        ],
        "stack_bundle_sha256": "1" * 64,
        "stack_image_evidence_sha256": "f" * 64,
        "stack_seed": seed,
        "stack_images": [image],
        "images": [image],
    }
    spec = {
        "stack": {
            "release_name": "galileo",
            "chart_version": "1.2.3",
            "chart_sha256": "b" * 64,
        },
        "galileoctl": {"enabled": False},
        "target": {
            "kube_context": "fixture",
            "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "c" * 64,
            "cluster_uid": "cluster-uid",
            "namespace": "galileo",
            "namespace_uid": "namespace-uid",
        },
    }
    current = {
        key: seed[key]
        for key in ("charts", "inputs", "redacted_render_sha256", "target", "items")
    }

    STACK_CONTRACT.validate_air_gap_contract(contract, spec, current)
    sources, owners = AIR_GAP.normalize_rendered_image_rows(
        [row], {"galileo": "galileo-stack"}, "shared Stack seed"
    )
    assert sources == {mirror}
    assert owners == {mirror: {"galileo-stack"}}
    AIR_GAP.require_image_architecture_coverage(
        [{"items": [row]}],
        [{"mirror": mirror, "architectures": ["amd64"]}],
        {"amd64", "arm64"},
    )


def test_chart_delete_risk_includes_stateful_claims_and_finalizers(
    tmp_path: Path,
) -> None:
    # The static inspectors must conservatively treat VCT/finalizers as delete risk.
    ac_source = (
        SKILLS / "galileo-on-prem-agent-control-setup/scripts/render_bundle.py"
    ).read_text(encoding="utf-8")
    luna_source = (
        SKILLS / "galileo-on-prem-luna-studio-setup/scripts/render_bundle.py"
    ).read_text(encoding="utf-8")
    for source in (ac_source, luna_source):
        assert 'b"volumeclaimtemplates"' in source
        assert 'b"finalizers:"' in source


def test_child_lifecycles_contain_no_helm_mutation_implementation() -> None:
    for path in (
        SKILLS / "galileo-on-prem-agent-control-setup/scripts/lifecycle.py",
        SKILLS / "galileo-on-prem-luna-studio-setup/scripts/lifecycle.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "--dry-run=server" in source
        assert 'cmd += ["install"' not in source
        assert 'cmd += ["upgrade"' not in source
        assert '"status": "applied"' not in source
        assert "is handoff-only" in source


def test_agent_control_rendered_outcome_rejects_chart_that_ignores_values() -> None:
    documents = [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "agent-control"},
            "spec": {
                "replicas": 2,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "agent-control",
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "128Mi"},
                                    "limits": {"cpu": "1", "memory": "1Gi"},
                                },
                            }
                        ]
                    }
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "agent-control"},
            "spec": {"ports": [{"port": 8000}]},
        },
    ]
    metadata = {
        "environment": "production",
        "resilience": {"hpa": True, "pdb": True, "network_policy": True},
        "routing": {
            "mode": "none",
            "external_url": "",
            "tls_secret_name": "",
            "ui_proxy_enabled": True,
        },
        "feature_flag": {"source": "central"},
    }
    rejects(lambda: AC_LIFECYCLE.agent_control_render_inventory(documents, metadata))


def test_luna_rendered_outcome_rejects_chart_that_ignores_values() -> None:
    documents = []
    for name in ("luna-studio-backend", "luna-studio"):
        documents.extend(
            [
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": name},
                    "spec": {
                        "template": {
                            "spec": {"containers": [{"name": name, "image": "fixture"}]}
                        }
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": name},
                    "spec": {"ports": [{"port": 80}]},
                },
            ]
        )
    metadata = {
        "secret_contracts": {
            "jwt": {"name": "luna-studio-jwt", "keys": ["jwt-secret-key"]},
            "admin": {"name": "luna-studio-admin", "keys": ["username", "password"]},
            "database": {"name": "luna-studio-database", "keys": ["connection-string"]},
            "nextauth": {"name": "luna-studio-nextauth", "keys": ["secret"]},
            "galileo_api": None,
            "object_auth": None,
            "remote": None,
        },
        "object_store": {"provider": "aws", "bucket": "fixture-bucket"},
        "routing": {
            "mode": "customer",
            "public_url": "https://luna.internal.example/",
            "tls_secret_name": "luna-tls",
        },
        "training": {
            "provider": "kubernetes",
            "gpu": {
                "enabled": False,
                "resource": "nvidia.com/gpu",
                "node_selector": {},
                "tolerations": [],
            },
        },
        "resilience": {"hpa": False, "pdb": False, "network_policy": False},
    }
    rejects(lambda: LUNA_LIFECYCLE.luna_render_inventory(documents, metadata))


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_route_validation_requires_exact_dns_and_tls_sets(lifecycle) -> None:
    expected_host = "app.internal.example"
    expected_secret = "app-tls"
    ingress = {
        "spec": {
            "rules": [{"host": expected_host, "http": {"paths": []}}],
            "tls": [{"secretName": expected_secret, "hosts": [expected_host]}],
        }
    }
    lifecycle.exact_ingress_tls(
        ingress, expected_host, expected_secret, "fixture Ingress"
    )
    suffix_trick = json.loads(json.dumps(ingress))
    suffix_trick["spec"]["rules"][0]["host"] = expected_host + ".evil.example"
    rejects(
        lambda: lifecycle.exact_ingress_tls(
            suffix_trick, expected_host, expected_secret, "fixture Ingress"
        )
    )
    wildcard = json.loads(json.dumps(ingress))
    wildcard["spec"]["tls"][0]["hosts"] = ["*.internal.example"]
    rejects(
        lambda: lifecycle.exact_ingress_tls(
            wildcard, expected_host, expected_secret, "fixture Ingress"
        )
    )
    extra_host = json.loads(json.dumps(ingress))
    extra_host["spec"]["rules"].append({"host": "other.internal.example"})
    rejects(
        lambda: lifecycle.exact_ingress_tls(
            extra_host, expected_host, expected_secret, "fixture Ingress"
        )
    )
    default_backend = json.loads(json.dumps(ingress))
    default_backend["spec"]["defaultBackend"] = {
        "service": {"name": "unexpected", "port": {"number": 80}}
    }
    rejects(
        lambda: lifecycle.exact_ingress_tls(
            default_backend, expected_host, expected_secret, "fixture Ingress"
        )
    )
    alias = json.loads(json.dumps(ingress))
    alias["metadata"] = {
        "annotations": {
            "nginx.ingress.kubernetes.io/server-alias": "other.internal.example"
        }
    }
    rejects(
        lambda: lifecycle.exact_ingress_tls(
            alias, expected_host, expected_secret, "fixture Ingress"
        )
    )

    route = {"spec": {"hostnames": [expected_host]}}
    lifecycle.exact_http_route_host(route, expected_host, "fixture HTTPRoute")
    route["spec"]["hostnames"].append("other.internal.example")
    rejects(
        lambda: lifecycle.exact_http_route_host(
            route, expected_host, "fixture HTTPRoute"
        )
    )


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_route_validation_rejects_hidden_or_extra_route_objects(
    lifecycle,
) -> None:
    ingress = {"kind": "Ingress", "metadata": {"name": "reviewed"}}
    assert lifecycle.exact_single_route([ingress], "Ingress", "fixture") is ingress
    rejects(
        lambda: lifecycle.exact_single_route(
            [ingress, {"kind": "HTTPRoute", "metadata": {"name": "unrelated"}}],
            "Ingress",
            "fixture",
        )
    )
    rejects(
        lambda: lifecycle.exact_single_route(
            [{"kind": "VirtualService", "metadata": {"name": "unrelated"}}],
            "Ingress",
            "fixture",
        )
    )


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_image_evidence_requires_digest_pinned_rendered_images(lifecycle) -> None:
    digest = "a" * 64
    documents = [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "fixture"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": f"registry.internal/app:1@sha256:{digest}",
                            }
                        ],
                        "initContainers": [
                            {
                                "name": "migration",
                                "image": f"registry.internal/migrate:1@sha256:{digest}",
                            }
                        ],
                    }
                }
            },
        }
    ]
    nodes = [
        {
            "metadata": {
                "name": "amd64-node",
                "labels": {
                    "kubernetes.io/arch": "amd64",
                    "pool": "general",
                },
            },
            "spec": {},
        },
        {
            "metadata": {
                "name": "arm64-node",
                "labels": {
                    "kubernetes.io/arch": "arm64",
                    "pool": "general",
                },
            },
            "spec": {},
        },
    ]
    items = lifecycle.rendered_image_items(documents, "fixture", nodes)
    assert [item["container_type"] for item in items] == [
        "container",
        "initContainer",
    ]
    assert all(item["eligible_architectures"] == ["amd64", "arm64"] for item in items)
    selected = json.loads(json.dumps(documents))
    selected[0]["spec"]["template"]["spec"]["nodeSelector"] = {
        "kubernetes.io/arch": "amd64"
    }
    selected_items = lifecycle.rendered_image_items(selected, "fixture", nodes)
    assert all(item["eligible_architectures"] == ["amd64"] for item in selected_items)
    unpinned = json.loads(json.dumps(documents))
    unpinned[0]["spec"]["template"]["spec"]["containers"][0]["image"] = (
        "registry.internal/app:1"
    )
    rejects(lambda: lifecycle.rendered_image_items(unpinned, "fixture", nodes))


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_architecture_evidence_matches_negative_affinity_and_rejects_bad_nodes(
    lifecycle,
) -> None:
    pod = {
        "affinity": {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {
                                    "key": "pool",
                                    "operator": "NotIn",
                                    "values": ["blocked"],
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }
    nodes = [
        {
            "metadata": {
                "name": "blocked-amd64",
                "labels": {
                    "kubernetes.io/arch": "amd64",
                    "pool": "blocked",
                },
            },
            "spec": {},
        },
        {
            "metadata": {
                "name": "unlabeled-arm64",
                "labels": {"kubernetes.io/arch": "arm64"},
            },
            "spec": {},
        },
    ]
    assert lifecycle.eligible_architectures(pod, nodes, "Deployment/fixture") == [
        "arm64"
    ]
    malformed = json.loads(json.dumps(nodes))
    malformed[0]["spec"] = []
    rejects(
        lambda: lifecycle.eligible_architectures(pod, malformed, "Deployment/fixture")
    )
    empty_term = json.loads(json.dumps(pod))
    empty_term["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"] = [{}]
    rejects(
        lambda: lifecycle.eligible_architectures(
            empty_term, nodes, "Deployment/fixture"
        )
    )
    empty_not_in = json.loads(json.dumps(pod))
    empty_not_in["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"][0]["matchExpressions"][0]["values"] = []
    rejects(
        lambda: lifecycle.eligible_architectures(
            empty_not_in, nodes, "Deployment/fixture"
        )
    )
    runtime_class = json.loads(json.dumps(pod))
    runtime_class["runtimeClassName"] = "gpu-runtime"
    rejects(
        lambda: lifecycle.eligible_architectures(
            runtime_class, nodes, "Deployment/fixture"
        )
    )


@pytest.mark.parametrize(
    ("lifecycle", "inventory_function"),
    (
        (AC_LIFECYCLE, "agent_control_render_inventory"),
        (LUNA_LIFECYCLE, "luna_render_inventory"),
    ),
)
def test_child_preflight_binds_server_admitted_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lifecycle, inventory_function: str
) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command: list[str], **kwargs):
        calls.append((command, kwargs))
        payload = b"client-render" if len(calls) == 1 else b"server-admitted-render"
        return types.SimpleNamespace(returncode=0, stdout=payload)

    monkeypatch.setattr(lifecycle, "KUBECONFIG_SNAPSHOT", "/private/kubeconfig")
    monkeypatch.setattr(lifecycle, "command_env", lambda: {"PATH": "/bin"})
    monkeypatch.setattr(lifecycle.shutil, "which", lambda name, path: f"/bin/{name}")
    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    monkeypatch.setattr(
        lifecycle,
        "rendered_documents",
        lambda payload: [{"observed": payload.decode("utf-8")}],
    )

    def inventory(documents: list[dict], metadata: dict) -> dict:
        assert documents == [{"observed": "server-admitted-render"}]
        assert metadata["release_name"] == "fixture"
        return {"observed": "server-admitted-render"}

    monkeypatch.setattr(lifecycle, inventory_function, inventory)
    monkeypatch.setattr(
        lifecycle,
        "redacted_render_sha256",
        lambda documents: "a" * 64,
    )
    result = lifecycle.server_dry_run(
        types.SimpleNamespace(for_action="install", kube_context="fixture"),
        {"release_name": "fixture", "namespace": "galileo"},
        tmp_path,
        tmp_path / "secret-values.yaml",
        chart_path=tmp_path / "chart.tgz",
    )
    assert len(calls) == 2
    assert "--output=yaml" in calls[1][0]
    assert calls[1][1]["input"] == b"client-render"
    assert result[1:] == ("a" * 64, [{"observed": "server-admitted-render"}])


@pytest.mark.parametrize("lifecycle", (AC_LIFECYCLE, LUNA_LIFECYCLE))
def test_child_endpoint_evidence_is_host_only_and_secret_safe(
    tmp_path: Path, lifecycle
) -> None:
    chart = tmp_path / "chart.tgz"
    chart_root = tmp_path / "chart"
    (chart_root / "templates").mkdir(parents=True)
    (chart_root / "Chart.yaml").write_text(
        "name: fixture\nversion: 1.2.3\n", encoding="utf-8"
    )
    (chart_root / "values.yaml").write_text(
        "serviceEndpoint: https://api.internal.example:8443/v1\n", encoding="utf-8"
    )
    (chart_root / "templates" / "deployment.yaml").write_text(
        "# endpoint: https://api.internal.example:8443/v1\n", encoding="utf-8"
    )
    with tarfile.open(chart, "w:gz") as archive:
        archive.add(chart_root, arcname="fixture")
    chart.chmod(0o600)
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "overlay.yaml"
    secret = tmp_path / "secret.yaml"
    base.write_text(
        "featureEndpoint: https://flags.internal.example/api\n", encoding="utf-8"
    )
    overlay.write_text("enabled: true\n", encoding="utf-8")
    sentinel = (
        "postgresql://sentinel-user:sentinel-pass@db.internal.example:5432/"
        "secret-path?token=sentinel-token"
    )
    secret.write_text(f'database_url: "{sentinel}"\n', encoding="utf-8")
    for path in (base, overlay, secret):
        path.chmod(0o600)
    encoded = __import__("base64").b64encode(sentinel.encode()).decode()
    documents = [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "fixture"},
            "data": {"database-url": encoded},
        }
    ]
    rows = lifecycle.rendered_endpoint_items(documents, chart, [base, overlay], secret)
    serialized = json.dumps(rows, sort_keys=True)
    assert "db.internal.example:5432" in serialized
    assert "api.internal.example:8443" in serialized
    assert "flags.internal.example" in serialized
    for forbidden in (
        "sentinel-user",
        "sentinel-pass",
        "secret-path",
        "sentinel-token",
        encoded,
        "postgresql://",
    ):
        assert forbidden not in serialized


def test_air_gap_rejects_endpoint_evidence_omitting_static_public_url(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "stack"
    values = bundle / "values"
    values.mkdir(parents=True, mode=0o700)
    bundle.chmod(0o700)
    nonsecret = values / "stack-values.yaml"
    nonsecret.write_text(
        "sentryEndpoint: https://evil.example.net/api\n", encoding="utf-8"
    )
    nonsecret.chmod(0o600)
    common = {
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": "a" * 64,
        "charts": [
            {
                "name": "galileo-stack",
                "release": "galileo",
                "version": "1.2.3",
                "sha256": "b" * 64,
            }
        ],
        "inputs": {
            "stack_nonsecret_values_sha256": "c" * 64,
            "stack_secret_contract_sha256": "d" * 64,
            "galileoctl_nonsecret_values_sha256": "",
            "galileoctl_secret_contract_sha256": "",
        },
        "redacted_render_sha256": "e" * 64,
        "target": {
            "context": "fixture",
            "api_server": "https://127.0.0.1:6443",
            "ca_sha256": "f" * 64,
            "kube_system_uid": "cluster-uid",
            "namespace": "galileo",
            "namespace_uid": "namespace-uid",
        },
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    image_evidence = {
        "schema": "galileo-on-prem-stack-rendered-image-inventory/v1",
        **common,
        "items": [],
    }
    endpoint_evidence = {
        "schema": "galileo-on-prem-stack-rendered-endpoint-inventory/v1",
        **common,
        "items": [],
    }
    evidence_path = tmp_path / "endpoint-evidence.json"
    raw = (json.dumps(endpoint_evidence, indent=2, sort_keys=True) + "\n").encode()
    evidence_path.write_bytes(raw)
    evidence_path.chmod(0o600)
    rejects(
        lambda: AIR_GAP.verified_stack_endpoint_evidence(
            str(evidence_path),
            hashlib.sha256(raw).hexdigest(),
            str(bundle),
            image_evidence,
        )
    )


def _chart_with_dynamic_dependency(
    tmp_path: Path,
    name: str,
    version: str,
    expression: str,
    template_name: str = "dynamic.yaml",
) -> Path:
    dependency = tmp_path / f"{name}-dependency"
    (dependency / "templates").mkdir(parents=True)
    (dependency / "Chart.yaml").write_text(
        "apiVersion: v2\nname: fixture-dependency\nversion: 1.0.0\nappVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (dependency / "templates" / template_name).write_text(
        expression + "\n", encoding="utf-8"
    )
    dependency_archive = tmp_path / "fixture-dependency.tgz"
    with tarfile.open(
        dependency_archive, "w:gz", format=tarfile.USTAR_FORMAT
    ) as archive:
        archive.add(dependency, arcname="fixture-dependency")
    parent = tmp_path / name
    (parent / "templates").mkdir(parents=True)
    (parent / "charts").mkdir()
    (parent / "Chart.yaml").write_text(
        f"apiVersion: v2\nname: {name}\nversion: {version}\nappVersion: {version}\n",
        encoding="utf-8",
    )
    (parent / "templates" / "deployment.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\n", encoding="utf-8"
    )
    (parent / "charts" / dependency_archive.name).write_bytes(
        dependency_archive.read_bytes()
    )
    output = tmp_path / f"{name}.tgz"
    with tarfile.open(output, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        archive.add(parent, arcname=name)
    output.chmod(0o600)
    return output


def _chart_with_root_dynamic(
    tmp_path: Path, name: str, version: str, expression: str
) -> Path:
    parent = tmp_path / name
    (parent / "templates").mkdir(parents=True)
    (parent / "Chart.yaml").write_text(
        f"apiVersion: v2\nname: {name}\nversion: {version}\nappVersion: {version}\n",
        encoding="utf-8",
    )
    (parent / "templates" / "dynamic.yaml").write_text(
        expression + "\n", encoding="utf-8"
    )
    output = tmp_path / f"{name}.tgz"
    with tarfile.open(output, "w:gz", format=tarfile.USTAR_FORMAT) as archive:
        archive.add(parent, arcname=name)
    output.chmod(0o600)
    return output


@pytest.mark.parametrize(
    "expression",
    (
        '{{ lookup "v1" "Secret" .Release.Namespace "fixture" }}',
        '{{- $secret := lookup "v1" "Secret" .Release.Namespace "fixture" -}}',
        "{{ tpl .Values.dynamic . }}",
        "{{ randAlphaNum 24 }}",
        '{{ shuffle "abcdef" }}',
        "{{ uuidv4 }}",
        '{{ now | date "2006-01-02" }}',
        '{{ env "HOME" }}',
        '{{ expandenv "${HOME}" }}',
        '{{ getHostByName "fixture.internal.example" }}',
        '{{ genPrivateKey "rsa" }}',
        "{{ .Capabilities.KubeVersion.Version }}",
        "{{ .Release.IsInstall }}",
        '{{ index . "Capabilities" }}',
        '{{ get . "Release" }}',
        "{{- $root := . -}}{{ $root.Release.IsUpgrade }}",
        '{{- $root := get (dict "root" .) "root" -}}{{- $files := index $root "Files" -}}{{ $files.Get "payload.yaml" }}',
        '{{ .Files.Get "payload.yaml" }}',
        '{{ .Files.GetBytes "payload.bin" }}',
        '{{ .Files.Glob "payloads/*" }}',
        '{{ .Files.Lines "payload.txt" }}',
        "{{ .Files.AsConfig }}",
        "{{ .Files.AsSecrets }}",
    ),
)
def test_optional_children_and_airgap_reject_nested_dynamic_helm(
    tmp_path: Path, expression: str
) -> None:
    ac_chart = _chart_with_dynamic_dependency(
        tmp_path, "agent-control", "1.2.3", expression
    )
    ac_artifact = AC_RENDER.secure_read(ac_chart, "Agent Control fixture")
    rejects(lambda: AC_RENDER.inspect_chart(ac_artifact, "1.2.3"))

    luna_tmp = tmp_path / "luna"
    luna_tmp.mkdir()
    luna_chart = _chart_with_dynamic_dependency(
        luna_tmp, "luna-studio", "2.1.5", expression
    )
    luna_artifact = LUNA_RENDER.secure_read(luna_chart, "Luna fixture")
    rejects(lambda: LUNA_RENDER.chart(luna_artifact, "2.1.5"))

    air_tmp = tmp_path / "air"
    air_tmp.mkdir()
    air_chart = _chart_with_dynamic_dependency(
        air_tmp, "galileo-stack", "1.2.3", expression
    )
    air_artifact = AIR_GAP.secure_file(air_chart, "Air-gap fixture")
    rejects(lambda: AIR_GAP.inspect_helm_chart(air_artifact, "galileo-stack", "1.2.3"))


@pytest.mark.parametrize(
    "expression",
    (
        "{{- $rendered := tpl .Values.payload . -}}",
        '{{ (.Files.Glob "payloads/*").AsSecrets }}',
    ),
)
def test_optional_children_and_airgap_reject_top_level_dynamic_helm(
    tmp_path: Path, expression: str
) -> None:
    ac_chart = _chart_with_root_dynamic(tmp_path, "agent-control", "1.2.3", expression)
    rejects(
        lambda: AC_RENDER.inspect_chart(
            AC_RENDER.secure_read(ac_chart, "Agent Control fixture"), "1.2.3"
        )
    )

    luna_tmp = tmp_path / "luna-root"
    luna_tmp.mkdir()
    luna_chart = _chart_with_root_dynamic(luna_tmp, "luna-studio", "2.1.5", expression)
    rejects(
        lambda: LUNA_RENDER.chart(
            LUNA_RENDER.secure_read(luna_chart, "Luna fixture"), "2.1.5"
        )
    )

    air_tmp = tmp_path / "air-root"
    air_tmp.mkdir()
    air_chart = _chart_with_root_dynamic(air_tmp, "galileo-stack", "1.2.3", expression)
    rejects(
        lambda: AIR_GAP.inspect_helm_chart(
            AIR_GAP.secure_file(air_chart, "Air-gap fixture"),
            "galileo-stack",
            "1.2.3",
        )
    )


def test_optional_inspectors_reject_dynamic_helm_in_arbitrary_template_suffix(
    tmp_path: Path,
) -> None:
    expression = '{{ bcrypt "fixture" }}'
    ac_chart = _chart_with_dynamic_dependency(
        tmp_path, "agent-control", "1.2.3", expression, "hidden.conf"
    )
    rejects(
        lambda: AC_RENDER.inspect_chart(
            AC_RENDER.secure_read(ac_chart, "Agent Control fixture"), "1.2.3"
        )
    )

    luna_tmp = tmp_path / "luna-arbitrary"
    luna_tmp.mkdir()
    luna_chart = _chart_with_dynamic_dependency(
        luna_tmp, "luna-studio", "2.1.5", expression, "hidden.conf"
    )
    rejects(
        lambda: LUNA_RENDER.chart(
            LUNA_RENDER.secure_read(luna_chart, "Luna fixture"), "2.1.5"
        )
    )

    air_tmp = tmp_path / "air-arbitrary"
    air_tmp.mkdir()
    air_chart = _chart_with_dynamic_dependency(
        air_tmp, "galileo-stack", "1.2.3", expression, "hidden.conf"
    )
    rejects(
        lambda: AIR_GAP.inspect_helm_chart(
            AIR_GAP.secure_file(air_chart, "Air-gap fixture"),
            "galileo-stack",
            "1.2.3",
        )
    )


def test_air_gap_discovers_literals_in_arbitrary_dependency_template_suffix(
    tmp_path: Path,
) -> None:
    body = (
        "apiVersion: v1\n"
        "kind: Pod\n"
        "image: registry.vendor.example/api:1.2.3\n"
        "endpoint: https://api.vendor.example:8443/v1\n"
    )
    chart = _chart_with_dynamic_dependency(
        tmp_path, "galileo-stack", "1.2.3", body, "hidden.conf"
    )
    report = AIR_GAP.inspect_helm_chart(
        AIR_GAP.secure_file(chart, "Air-gap fixture"),
        "galileo-stack",
        "1.2.3",
    )
    assert report["declared_image_references"] == ["registry.vendor.example/api:1.2.3"]
    bundle = tmp_path / "bundle"
    artifacts = bundle / "artifacts"
    artifacts.mkdir(parents=True, mode=0o700)
    bundled_chart = artifacts / "galileo-stack.tgz"
    bundled_chart.write_bytes(chart.read_bytes())
    bundled_chart.chmod(0o600)
    assert "api.vendor.example:8443" in AIR_GAP.static_endpoint_hosts(bundle)


def child_evidence_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate=None,
):
    component = "agent-control"
    bundle_sha = "a" * 64
    parent_sha = "b" * 64
    chart_sha = "c" * 64
    target = {
        "context": "fixture",
        "api_server": "https://127.0.0.1:6443",
        "ca_sha256": "d" * 64,
        "kube_system_uid": "cluster-uid",
        "namespace": "galileo",
        "namespace_uid": "namespace-uid",
    }
    child_target = {key: value for key, value in target.items() if key != "namespace"}
    bundle = tmp_path / "child-bundle"
    (bundle / "values").mkdir(parents=True, mode=0o700)
    bundle.chmod(0o700)
    overlay = bundle / "values" / "agent-control-overlay.yaml"
    overlay.write_text("enabled: true\n", encoding="utf-8")
    overlay.chmod(0o600)
    metadata = {
        "bundle_sha256": bundle_sha,
        "ownership": "standalone",
        "namespace": "galileo",
        "release_name": component,
        "base_values_sha256": "e" * 64,
        "parent_stack": {"bundle_sha256": parent_sha, "target": child_target},
        "chart": {"name": component, "version": "1.2.3", "sha256": chart_sha},
    }

    class Loader:
        @staticmethod
        def exec_module(module) -> None:
            module.validate_bundle = lambda _: metadata

    fake_spec = types.SimpleNamespace(name="fake_child_renderer", loader=Loader())
    monkeypatch.setattr(
        AIR_GAP.importlib.util, "spec_from_file_location", lambda *_: fake_spec
    )
    monkeypatch.setattr(
        AIR_GAP.importlib.util, "module_from_spec", lambda _: types.SimpleNamespace()
    )
    digest = "f" * 64
    evidence = {
        "schema": "galileo-on-prem-child-rendered-image-inventory/v1",
        "generated_by": "galileo-on-prem-agent-control-setup",
        "component": component,
        "source_bundle_sha256": bundle_sha,
        "parent_stack_bundle_sha256": parent_sha,
        "chart": {
            "name": component,
            "release": component,
            "version": "1.2.3",
            "sha256": chart_sha,
        },
        "inputs": {
            "base_values_sha256": "e" * 64,
            "overlay_values_sha256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
            "secret_input_contract": redacted_secret_contract(),
        },
        "render_inventory_sha256": "1" * 64,
        "redacted_render_sha256": "2" * 64,
        "target": child_target,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "items": [
            {
                "release": component,
                "source_object": "Deployment/agent-control",
                "container_type": "container",
                "container": "agent-control",
                "image": f"registry.vendor.example/ac:1.2.3@sha256:{digest}",
                "digest": f"sha256:{digest}",
                "eligible_architectures": ["amd64"],
            }
        ],
    }
    if mutate:
        mutate(evidence)
    evidence_path = tmp_path / "child-images.json"
    raw = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    evidence_path.write_bytes(raw)
    evidence_path.chmod(0o600)
    endpoint_evidence = {
        key: value for key, value in evidence.items() if key != "items"
    }
    endpoint_evidence["schema"] = "galileo-on-prem-child-rendered-endpoint-inventory/v1"
    endpoint_evidence["items"] = [
        {
            "host": "registry.internal.example",
            "purpose": "fixture endpoint",
            "source": "rendered:Deployment/agent-control",
        }
    ]
    endpoint_path = tmp_path / "child-endpoints.json"
    endpoint_raw = (
        json.dumps(endpoint_evidence, indent=2, sort_keys=True) + "\n"
    ).encode()
    endpoint_path.write_bytes(endpoint_raw)
    endpoint_path.chmod(0o600)
    entry = {
        "component": component,
        "bundle": str(bundle),
        "bundle_sha256": bundle_sha,
        "evidence_file": str(evidence_path),
        "evidence_sha256": hashlib.sha256(raw).hexdigest(),
        "endpoint_evidence_file": str(endpoint_path),
        "endpoint_evidence_sha256": hashlib.sha256(endpoint_raw).hexdigest(),
    }
    return entry, parent_sha, target


def test_air_gap_accepts_exact_child_image_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, parent_sha, target = child_evidence_fixture(tmp_path, monkeypatch)
    chart, sources, _, owners, endpoint_document, endpoint_rows = (
        AIR_GAP.verified_child_evidence(entry, parent_sha, target)
    )
    assert chart["name"] == "agent-control"
    assert sources == {"registry.vendor.example/ac:1.2.3"}
    assert owners == {"registry.vendor.example/ac:1.2.3": {"agent-control"}}
    assert endpoint_document["component"] == "agent-control"
    assert endpoint_rows[0]["host"] == "registry.internal.example"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda evidence: evidence.update(items=[]),
        lambda evidence: evidence["items"].append(dict(evidence["items"][0])),
        lambda evidence: evidence["items"][0].update(
            source_object="ConfigMap/not-a-workload"
        ),
        lambda evidence: evidence.update(
            created_at=(datetime.now(timezone.utc) - timedelta(hours=25))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        lambda evidence: evidence["target"].update(namespace_uid="wrong"),
        lambda evidence: evidence["chart"].update(version="9.9.9"),
        lambda evidence: evidence["inputs"].update(secret_values_sha256="0" * 64),
        lambda evidence: evidence["inputs"]["secret_input_contract"]["leaves"][
            0
        ].update(shape=True),
    ),
)
def test_air_gap_rejects_malformed_stale_or_wrong_object_child_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation
) -> None:
    entry, parent_sha, target = child_evidence_fixture(
        tmp_path, monkeypatch, mutate=mutation
    )
    rejects(lambda: AIR_GAP.verified_child_evidence(entry, parent_sha, target))


def test_air_gap_requires_complete_enabled_child_union() -> None:
    optional = {"agent-control": "standalone", "luna-studio": "disabled"}
    rejects(lambda: AIR_GAP.require_child_evidence_coverage(optional, set()))
    AIR_GAP.require_child_evidence_coverage(optional, {"agent-control"})
    rejects(
        lambda: AIR_GAP.require_child_evidence_coverage(
            optional, {"agent-control", "luna-studio"}
        )
    )


def test_air_gap_expanded_union_render_and_offline_verify_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise immutable output wiring for Stack seed + one standalone child."""

    def write_json(path: Path, value: object, mode: int = 0o600) -> str:
        raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        path.write_bytes(raw)
        path.chmod(mode)
        return hashlib.sha256(raw).hexdigest()

    def write_file(path: Path, value: bytes, mode: int = 0o600) -> str:
        path.write_bytes(value)
        path.chmod(mode)
        return hashlib.sha256(value).hexdigest()

    stack_bundle_sha = "1" * 64
    stack_chart_sha = write_file(tmp_path / "galileo-stack.tgz", b"stack-chart")
    child_chart_sha = write_file(tmp_path / "agent-control.tgz", b"child-chart")
    stack_digest = "sha256:" + "2" * 64
    child_digest = "sha256:" + "3" * 64
    stack_source = "vendor.example/stack:1.2.3"
    child_source = "vendor.example/agent-control:1.2.3"
    stack_mirror = "registry.internal.example/galileo/stack:1.2.3"
    child_mirror = "registry.internal.example/galileo/agent-control:1.2.3"
    stack_target = {
        "context": "fixture",
        "api_server": "https://127.0.0.1:6443",
        "ca_sha256": "4" * 64,
        "kube_system_uid": "cluster-uid",
        "namespace": "galileo",
        "namespace_uid": "namespace-uid",
    }
    child_target = {
        key: value for key, value in stack_target.items() if key != "namespace"
    }
    created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    created_at = created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stack_evidence = {
        "schema": "galileo-on-prem-stack-rendered-image-inventory/v1",
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": stack_bundle_sha,
        "charts": [
            {
                "name": "galileo-stack",
                "release": "galileo",
                "version": "1.2.3",
                "sha256": stack_chart_sha,
            }
        ],
        "inputs": {
            "stack_nonsecret_values_sha256": "5" * 64,
            "stack_secret_contract_sha256": "6" * 64,
            "galileoctl_nonsecret_values_sha256": "",
            "galileoctl_secret_contract_sha256": "",
        },
        "redacted_render_sha256": "7" * 64,
        "target": stack_target,
        "created_at": created_at,
        "items": [
            {
                "release": "galileo",
                "source_object": "Deployment/api",
                "container_type": "container",
                "container": "api",
                "image": f"{stack_mirror}@{stack_digest}",
                "digest": stack_digest,
                "eligible_architectures": ["amd64"],
            }
        ],
    }
    stack_evidence_path = tmp_path / "stack-images.json"
    stack_evidence_sha = write_json(stack_evidence_path, stack_evidence)
    stack_endpoint_evidence = {
        key: value for key, value in stack_evidence.items() if key != "items"
    }
    stack_endpoint_evidence["schema"] = (
        "galileo-on-prem-stack-rendered-endpoint-inventory/v1"
    )
    stack_endpoint_evidence["items"] = [
        {
            "host": "registry.internal.example",
            "purpose": "fixture endpoint",
            "source": "rendered:Deployment/api",
        }
    ]
    stack_endpoint_path = tmp_path / "stack-endpoints.json"
    stack_endpoint_sha = write_json(stack_endpoint_path, stack_endpoint_evidence)
    child_bundle_sha = "8" * 64
    child_evidence = {
        "schema": "galileo-on-prem-child-rendered-image-inventory/v1",
        "generated_by": "galileo-on-prem-agent-control-setup",
        "component": "agent-control",
        "source_bundle_sha256": child_bundle_sha,
        "parent_stack_bundle_sha256": stack_bundle_sha,
        "chart": {
            "name": "agent-control",
            "release": "agent-control",
            "version": "1.2.3",
            "sha256": child_chart_sha,
        },
        "inputs": {
            "base_values_sha256": "9" * 64,
            "overlay_values_sha256": "a" * 64,
            "secret_input_contract": redacted_secret_contract(),
        },
        "render_inventory_sha256": "b" * 64,
        "redacted_render_sha256": "c" * 64,
        "target": child_target,
        "created_at": created_at,
        "items": [
            {
                "release": "agent-control",
                "source_object": "Job/agent-control-migrate",
                "container_type": "container",
                "container": "migration",
                "image": f"{child_mirror}@{child_digest}",
                "digest": child_digest,
                "eligible_architectures": ["amd64"],
            }
        ],
    }
    child_evidence_path = tmp_path / "child-images.json"
    child_evidence_sha = write_json(child_evidence_path, child_evidence)
    child_endpoint_evidence = {
        key: value for key, value in child_evidence.items() if key != "items"
    }
    child_endpoint_evidence["schema"] = (
        "galileo-on-prem-child-rendered-endpoint-inventory/v1"
    )
    child_endpoint_evidence["items"] = [
        {
            "host": "registry.internal.example",
            "purpose": "fixture endpoint",
            "source": "rendered:Job/agent-control-migrate",
        }
    ]
    child_endpoint_path = tmp_path / "child-endpoints.json"
    child_endpoint_sha = write_json(child_endpoint_path, child_endpoint_evidence)
    stack_bundle = tmp_path / "stack-bundle"
    child_bundle = tmp_path / "child-bundle"
    stack_bundle.mkdir(mode=0o700)
    child_bundle.mkdir(mode=0o700)
    stack_archive = tmp_path / "stack.oci.tar"
    child_archive = tmp_path / "child.oci.tar"
    stack_archive_sha = write_file(stack_archive, b"stack-oci")
    child_archive_sha = write_file(child_archive, b"child-oci")
    cli = tmp_path / "galileoctl"
    cli_sha = write_file(cli, b"fixture-cli")

    scans = []
    for index, (digest, subject) in enumerate(
        ((stack_digest, stack_source), (child_digest, child_source))
    ):
        scan_path = tmp_path / f"scan-{index}.json"
        scan = {
            "schema": "galileo-image-scan-attestation/v1",
            "subject": subject,
            "image_digest": digest,
            "passed": True,
            "scanner": "fixture-scanner",
            "scanner_version": "1.0.0",
            "scanned_at": created_at,
            "policy": "reviewed fixture policy",
        }
        scans.append((scan_path, write_json(scan_path, scan)))
    image_manifest = {
        "schema": "galileo-air-gap-image-manifest/v1",
        "release": "fixture-1.2.3",
        "images": [
            {
                "source": stack_source,
                "source_digest": stack_digest,
                "mirror": stack_mirror,
                "mirror_digest": stack_digest,
                "archive": str(stack_archive),
                "archive_sha256": stack_archive_sha,
                "architectures": ["amd64"],
                "uses": ["runtime"],
                "scan_attestation_file": str(scans[0][0]),
                "scan_attestation_sha256": scans[0][1],
            },
            {
                "source": child_source,
                "source_digest": child_digest,
                "mirror": child_mirror,
                "mirror_digest": child_digest,
                "archive": str(child_archive),
                "archive_sha256": child_archive_sha,
                "architectures": ["amd64"],
                "uses": ["job"],
                "scan_attestation_file": str(scans[1][0]),
                "scan_attestation_sha256": scans[1][1],
            },
        ],
    }
    image_manifest_path = tmp_path / "image-manifest.json"
    image_manifest_sha = write_json(image_manifest_path, image_manifest)
    category_evidence = {
        use: {
            "count": 1 if use in {"runtime", "job"} else 0,
            "empty_reason": "" if use in {"runtime", "job"} else "not used",
        }
        for use in AIR_GAP.USES
    }
    chart_inventory = {
        "schema": "galileo-chart-image-inventory/v1",
        "release": "fixture-1.2.3",
        "generated_by": {
            "tool": "galileo-on-prem-stack-setup",
            "stack_bundle_sha256": stack_bundle_sha,
        },
        "charts": [
            {
                "name": "agent-control",
                "version": "1.2.3",
                "sha256": child_chart_sha,
            },
            {
                "name": "galileo-stack",
                "version": "1.2.3",
                "sha256": stack_chart_sha,
            },
        ],
        "images": [
            {"source": child_source, "use": "job"},
            {"source": stack_source, "use": "runtime"},
        ],
        "use_categories": category_evidence,
    }
    chart_inventory_path = tmp_path / "chart-inventory.json"
    chart_inventory_sha = write_json(chart_inventory_path, chart_inventory)
    stack_chart = {
        "name": "galileo-stack",
        "version": "1.2.3",
        "sha256": stack_chart_sha,
    }
    child_chart = {
        "name": "agent-control",
        "version": "1.2.3",
        "sha256": child_chart_sha,
    }

    def fake_stack(raw, expected, evidence_raw, evidence_expected):
        assert expected == stack_bundle_sha
        assert evidence_expected == stack_evidence_sha
        document = json.loads(Path(evidence_raw).read_text(encoding="utf-8"))
        return (
            stack_bundle_sha,
            [stack_chart],
            {stack_mirror},
            document,
            {stack_mirror: {"galileo-stack"}},
        )

    def fake_child(entry, expected_parent, expected_target):
        assert expected_parent == stack_bundle_sha
        assert expected_target == stack_target
        document = json.loads(Path(entry["evidence_file"]).read_text(encoding="utf-8"))
        endpoint_document = json.loads(
            Path(entry["endpoint_evidence_file"]).read_text(encoding="utf-8")
        )
        return (
            child_chart,
            {child_mirror},
            document,
            {child_mirror: {"agent-control"}},
            endpoint_document,
            endpoint_document["items"],
        )

    archive_identities = {
        stack_archive_sha: {"root_digest": stack_digest, "architectures": ["amd64"]},
        child_archive_sha: {"root_digest": child_digest, "architectures": ["amd64"]},
    }
    monkeypatch.setattr(AIR_GAP, "verified_stack_evidence", fake_stack)
    monkeypatch.setattr(
        AIR_GAP,
        "verified_stack_endpoint_evidence",
        lambda raw, expected, stack_bundle_raw, image_document: (
            json.loads(Path(raw).read_text(encoding="utf-8")),
            json.loads(Path(raw).read_text(encoding="utf-8"))["items"],
        ),
    )
    monkeypatch.setattr(AIR_GAP, "verified_child_evidence", fake_child)
    monkeypatch.setattr(
        AIR_GAP, "oci_identity", lambda artifact: archive_identities[artifact.sha256]
    )
    monkeypatch.setattr(AIR_GAP, "linux_elf_arch", lambda _: "amd64")
    monkeypatch.setattr(
        AIR_GAP,
        "inspect_helm_chart",
        lambda artifact, name, version: {
            "type": "helm-chart",
            "members": 2,
            "expanded_bytes": 10,
            "root": name,
            "name": name,
            "version": version,
            "app_version": "1.2.3",
            "declared_image_references": [],
        },
    )
    spec = {
        "api_version": "galileo-on-prem-air-gap-setup/v1",
        "galileo": {"console_url": ""},
        "release": {
            "id": "fixture-1.2.3",
            "environment": "production",
            "target_architectures": ["amd64"],
            "optional_components": {
                "agent-control": "standalone",
                "luna-studio": "disabled",
            },
        },
        "registry": {
            "destination": "registry.internal.example/galileo",
            "internal_dns_suffixes": ["internal.example"],
            "exact_internal_hosts": ["registry.internal.example"],
        },
        "artifacts": {
            "image_manifest_file": str(image_manifest_path),
            "image_manifest_sha256": image_manifest_sha,
            "chart_inventory_file": str(chart_inventory_path),
            "chart_inventory_sha256": chart_inventory_sha,
            "stack_bundle": str(stack_bundle),
            "stack_bundle_sha256": stack_bundle_sha,
            "stack_image_evidence_file": str(stack_evidence_path),
            "stack_image_evidence_sha256": stack_evidence_sha,
            "stack_endpoint_evidence_file": str(stack_endpoint_path),
            "stack_endpoint_evidence_sha256": stack_endpoint_sha,
            "child_image_evidence": [
                {
                    "component": "agent-control",
                    "bundle": str(child_bundle),
                    "bundle_sha256": child_bundle_sha,
                    "evidence_file": str(child_evidence_path),
                    "evidence_sha256": child_evidence_sha,
                    "endpoint_evidence_file": str(child_endpoint_path),
                    "endpoint_evidence_sha256": child_endpoint_sha,
                }
            ],
            "charts": [
                {
                    "name": "agent-control",
                    "version": "1.2.3",
                    "file": str(tmp_path / "agent-control.tgz"),
                    "sha256": child_chart_sha,
                },
                {
                    "name": "galileo-stack",
                    "version": "1.2.3",
                    "file": str(tmp_path / "galileo-stack.tgz"),
                    "sha256": stack_chart_sha,
                },
            ],
            "galileoctl": {
                "version": "1.2.3",
                "file": str(cli),
                "sha256": cli_sha,
                "os": "linux",
                "architecture": "amd64",
            },
            "models": [],
        },
        "no_egress": {
            "strict": True,
            "internal_dns_suffixes": ["internal.example"],
            "exact_internal_hosts": ["registry.internal.example"],
            "allowed_endpoints": ["registry.internal.example"],
        },
        "approval": {
            "cse_reference": "CSE-fixture",
            "release_manifest_approved": True,
        },
    }
    spec_path = tmp_path / "spec.json"
    write_json(spec_path, spec)
    output = tmp_path / "bundle"
    args = types.SimpleNamespace(
        spec=str(spec_path),
        output_dir=str(output),
        galileo_console_url="https://console.demo-v2.galileocloud.io/",
    )
    AIR_GAP.render(args)
    metadata = AIR_GAP.verify_bundle(output)
    assert metadata["optional_components"]["agent-control"] == "standalone"
    assert {item["source"] for item in metadata["images"]} == {
        stack_source,
        child_source,
    }
    assert {item["source"] for item in metadata["stack_images"]} == {stack_source}
    assert {item["source"] for item in metadata["child_images"]} == {child_source}
    assert metadata["stack_images"][0]["mirror"] == stack_mirror
    assert metadata["stack_images"][0]["source"] != stack_mirror
    assert metadata["child_images"][0]["mirror"] == child_mirror
    assert metadata["child_images"][0]["source"] != child_mirror
    assert metadata["open_gates"] == ["endpoint_rewrite_evidence_missing"]
    assert metadata["registry_push_execution"] == ("galileo-cse-operator-handoff-only")
    report = json.loads((output / "no-egress-report.json").read_text(encoding="utf-8"))
    assert report["strict"] is False
    assert report["unvalidated_gates"] == ["endpoint_rewrite_evidence_missing"]
    coverage = json.loads((output / "coverage-report.json").read_text(encoding="utf-8"))
    assert coverage["uncovered"] == ["endpoint_rewrite_evidence_missing"]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "supply_chain.py",
            "--verify",
            "--bundle",
            str(output),
            "--galileo-console-url",
            "https://console.demo-v2.galileocloud.io/",
        ],
    )
    with pytest.raises(SystemExit, match="endpoint_rewrite_evidence_missing"):
        AIR_GAP.main()

#!/usr/bin/env python3
"""Production-boundary tests for the Lemonade collector transaction helper."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/lemonade-splunk-otel/scripts/transactional_apply.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lemonade_transactional_apply", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tx() -> ModuleType:
    return load_module()


def make_args(
    staged: Path,
    live: Path,
    state_root: Path,
    *,
    expected: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        staged=str(staged),
        live=str(live),
        service="splunk-otel-collector.service",
        health_url="http://127.0.0.1:13133/",
        expected_sha256=expected or hashlib.sha256(staged.read_bytes()).hexdigest(),
        collector_binary=str(staged.parent / "otelcol"),
        collector_binary_sha256="1" * 64,
        state_root=str(state_root),
        health_timeout=3.0,
    )


def prepare_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path.resolve()
    staged = root / "staged.yaml"
    live = root / "collector.yaml"
    state_root = root / "transactions"
    staged.write_bytes(b"receivers:\n  otlp: {}\n")
    live.write_bytes(b"receivers:\n  hostmetrics: {}\n")
    live.chmod(0o640)
    return staged, live, state_root


def load_journal(applied: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(Path(applied["manifest"]).read_text(encoding="utf-8"))
    return json.loads(Path(manifest["journal_path"]).read_text(encoding="utf-8"))


def mock_service_layer(
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    *,
    active: bool = True,
    enabled: bool = True,
) -> tuple[list[str], list[str]]:
    actions: list[str] = []
    state_queries: list[str] = []
    monkeypatch.setattr(tx, "systemctl_path", lambda: "/mock/systemctl")

    def boolean(_systemctl: str, operation: str, _service: str) -> bool:
        state_queries.append(operation)
        return active if operation == "is-active" else enabled

    monkeypatch.setattr(tx, "service_boolean", boolean)
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda _systemctl, _service: {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": "active" if active else "inactive",
            "unit_file_state": "enabled" if enabled else "disabled",
        },
    )
    monkeypatch.setattr(
        tx,
        "package_versions",
        lambda: {
            "lemonade-server": "10.10.0",
            "splunk-otel-collector": "0.156.0",
        },
    )
    monkeypatch.setattr(tx, "host_fingerprint", lambda: "3" * 64)
    monkeypatch.setattr(tx, "service_unit_fingerprint", lambda *_args: "2" * 64)
    monkeypatch.setattr(
        tx,
        "collector_binary_provenance",
        lambda path, expected, **_kwargs: {
            "path": str(path),
            "sha256": expected,
            "device": 1,
            "inode": 2,
        },
    )
    monkeypatch.setattr(
        tx, "assert_root_owned_secure_path", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda _systemctl, action, _service: actions.append(action),
    )
    monkeypatch.setattr(
        tx,
        "wait_for_health",
        lambda _url, _timeout: {"checked": True, "ok": True, "status_code": 200},
    )
    return actions, state_queries


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:13133/",
        "http://localhost:13133/",
        "http://192.168.1.4:13133/",
        "http://user:pass@127.0.0.1:13133/",
        "http://127.0.0.1/",
        "http://127.0.0.1:13133/?token=secret",
        "http://127.0.0.1:13133/#fragment",
        "http://127.0.0.1:13133/%0a",
    ],
)
def test_health_url_rejects_nonliteral_nonloopback_or_credential_forms(
    tx: ModuleType, url: str
) -> None:
    with pytest.raises(tx.TransactionError):
        tx.validate_loopback_health_url(url)


def test_health_url_accepts_ipv4_and_ipv6_loopback(tx: ModuleType) -> None:
    assert tx.validate_loopback_health_url("http://127.0.0.1:13133/")
    assert tx.validate_loopback_health_url("http://[::1]:13133/health")


def test_private_artifact_metadata_requires_exact_root_0600(tx: ModuleType) -> None:
    safe = SimpleNamespace(st_uid=0, st_gid=0, st_mode=stat.S_IFREG | 0o600, st_nlink=1)
    tx.validate_private_artifact_metadata(safe, label="artifact")
    for field, value in (
        ("st_uid", 1000),
        ("st_gid", 1000),
        ("st_mode", stat.S_IFREG | 0o640),
        ("st_nlink", 2),
    ):
        unsafe = SimpleNamespace(**vars(safe))
        setattr(unsafe, field, value)
        with pytest.raises(tx.TransactionError, match="mode 0600"):
            tx.validate_private_artifact_metadata(unsafe, label="artifact")


def test_apply_rejects_expected_live_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    args = make_args(staged, live, state_root)
    args.expected_live_sha256 = "0" * 64
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(args)
    assert raised.value.code == "live_hash_mismatch"


def test_regular_file_reader_rejects_symlink_and_hardlink(
    tmp_path: Path, tx: ModuleType
) -> None:
    original = tmp_path / "original"
    original.write_bytes(b"value")
    symlink = tmp_path / "symlink"
    symlink.symlink_to(original)
    with pytest.raises(tx.TransactionError, match="symbolic link"):
        tx.read_regular_file(symlink, label="input", max_bytes=100)

    hardlink = tmp_path / "hardlink"
    os.link(original, hardlink)
    with pytest.raises(tx.TransactionError, match="single-link"):
        tx.read_regular_file(original, label="input", max_bytes=100)


def test_trusted_path_rejects_nonroot_or_group_writable_ancestor(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    target = Path("/secure/collector/config.yaml")

    def metadata(path: Path, *, insecure: str | None = None) -> Any:
        is_file = path == target
        mode = 0o100640 if is_file else 0o040755
        uid = 0
        if insecure == "writable" and path == Path("/secure"):
            mode = 0o040775
        if insecure == "owner" and path == Path("/secure/collector"):
            uid = 1000
        return SimpleNamespace(st_mode=mode, st_uid=uid)

    monkeypatch.setattr(tx.os, "lstat", lambda path: metadata(Path(path)))
    tx.assert_root_owned_secure_path(target, label="live config", include_final=True)

    monkeypatch.setattr(
        tx.os, "lstat", lambda path: metadata(Path(path), insecure="writable")
    )
    with pytest.raises(tx.TransactionError, match="root-owned"):
        tx.assert_root_owned_secure_path(
            target, label="live config", include_final=True
        )

    monkeypatch.setattr(
        tx.os, "lstat", lambda path: metadata(Path(path), insecure="owner")
    )
    with pytest.raises(tx.TransactionError, match="root-owned"):
        tx.assert_root_owned_secure_path(
            target, label="live config", include_final=True
        )


def test_xattr_snapshot_round_trips_acl_selinux_and_arbitrary_metadata(
    tx: ModuleType,
) -> None:
    expected = {
        "security.selinux": b"system_u:object_r:etc_t:s0\x00",
        "system.posix_acl_access": b"\x02\x00acl-bytes",
        "user.owner": b"collector",
    }
    assert tx.decode_xattrs(tx.encode_xattrs(expected)) == expected


def test_atomic_install_rejects_metadata_failure_before_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    live = tmp_path.resolve() / "collector.yaml"
    live.write_bytes(b"original\n")
    original = live.read_bytes()
    monkeypatch.setattr(
        tx, "assert_root_owned_secure_path", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        tx,
        "apply_xattrs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            tx.TransactionError(
                "metadata_restore_failed", "live config metadata cannot be restored"
            )
        ),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.atomic_install(
            live,
            b"replacement\n",
            uid=os.geteuid(),
            gid=os.getegid(),
            mode=0o640,
            xattrs={"security.selinux": b"label"},
        )
    assert raised.value.code == "metadata_restore_failed"
    assert live.read_bytes() == original


def test_transaction_snapshots_and_reapplies_nontrivial_xattrs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    expected = {
        "security.selinux": b"system_u:object_r:etc_t:s0\x00",
        "system.posix_acl_access": b"acl",
    }
    applied_xattrs: list[dict[str, bytes]] = []
    mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(tx, "read_xattrs", lambda *_args, **_kwargs: dict(expected))
    monkeypatch.setattr(
        tx,
        "apply_xattrs",
        lambda _path, value: applied_xattrs.append(dict(value)),
    )

    applied = tx.apply_transaction(make_args(staged, live, state_root))
    manifest = json.loads(Path(applied["manifest"]).read_text(encoding="utf-8"))
    snapshot = Path(manifest["xattrs_path"])
    assert tx.decode_xattrs(snapshot.read_bytes()) == expected
    restored = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert restored["ok"] is True
    assert expected in applied_xattrs


def test_apply_snapshots_installs_and_records_only_selected_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    original_stat = live.stat()
    actions, queries = mock_service_layer(monkeypatch, tx)

    result = tx.apply_transaction(make_args(staged, live, state_root))

    assert result["ok"] is True
    assert live.read_bytes() == staged.read_bytes()
    installed_stat = live.stat()
    assert stat.S_IMODE(installed_stat.st_mode) == 0o640
    assert (installed_stat.st_uid, installed_stat.st_gid) == (
        original_stat.st_uid,
        original_stat.st_gid,
    )
    assert actions == ["restart"]
    assert queries == ["is-active"] * 7

    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = Path(manifest["backup_path"])
    assert backup.read_bytes() == original
    assert stat.S_IMODE(state_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert manifest["backup_sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["service"]["was_active"] is True
    assert manifest["service"]["was_enabled"] is True
    assert manifest["service"]["active_state"] == "active"
    assert manifest["service"]["unit_file_state"] == "enabled"
    assert manifest["package_versions"] == {
        "lemonade-server": "10.10.0",
        "splunk-otel-collector": "0.156.0",
    }
    assert manifest["schema_version"] == "lemonade-collector-transaction/v2"
    assert manifest["host_fingerprint"] == "3" * 64
    assert manifest["service_unit_fingerprint"] == "2" * 64
    assert manifest["collector_binary"]["sha256"] == "1" * 64
    assert load_journal(result)["phase"] == "applied"
    current = json.loads((state_root / "current.json").read_text(encoding="utf-8"))
    assert current["generation"] == manifest["generation"]
    assert current["manifest_path"] == str(manifest_path)
    serialized = json.dumps(manifest)
    assert "Environment=" not in serialized
    assert "ExecStart=" not in serialized
    assert "systemctl cat" not in serialized
    assert "FragmentPath" not in serialized
    assert "DropInPaths" not in serialized


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"load_state": "loaded"},
        {"id": "different.service", "load_state": "loaded"},
        {"id": "splunk-otel-collector.service"},
        {"id": "splunk-otel-collector.service", "load_state": "not-found"},
        {"id": "splunk-otel-collector.service", "load_state": "error"},
    ],
)
def test_apply_requires_exact_loaded_systemd_unit_before_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    metadata: dict[str, str],
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, queries = mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(tx, "service_metadata", lambda *_args: metadata)
    monkeypatch.setattr(
        tx,
        "package_versions",
        lambda: pytest.fail("packages must not be queried for an unresolved unit"),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "service_metadata_failed"
    assert live.read_bytes() == original
    assert not list(state_root.glob("transaction-*"))
    assert queries == []
    assert actions == []


@pytest.mark.parametrize(
    "active_state",
    ["activating", "deactivating", "failed", "maintenance", "reloading"],
)
def test_apply_rejects_transitional_failed_or_other_active_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    active_state: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda *_args: {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": active_state,
            "unit_file_state": "enabled",
        },
    )
    monkeypatch.setattr(
        tx,
        "service_boolean",
        lambda *_args: pytest.fail("unsupported ActiveState must fail first"),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))
    assert raised.value.code == "unsupported_active_state"
    assert live.read_bytes() == original


@pytest.mark.parametrize(
    "unit_file_state",
    ["enabled-runtime", "static", "alias", "linked", "indirect", "masked"],
)
def test_apply_rejects_nonpersistent_or_ambiguous_unit_file_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    unit_file_state: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda *_args: {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": "active",
            "unit_file_state": unit_file_state,
        },
    )
    monkeypatch.setattr(
        tx,
        "service_boolean",
        lambda *_args: pytest.fail(
            "enabled-runtime/static/alias must not collapse to a boolean"
        ),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))
    assert raised.value.code == "unsupported_unit_file_state"


@pytest.mark.parametrize(
    ("active_state", "is_active"), [("active", False), ("inactive", True)]
)
def test_apply_rejects_active_state_and_is_active_disagreement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    active_state: str,
    is_active: bool,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda *_args: {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": active_state,
            "unit_file_state": "enabled",
        },
    )
    monkeypatch.setattr(tx, "service_boolean", lambda *_args: is_active)

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))
    assert raised.value.code == "service_state_disagreement"


def test_apply_does_not_restart_or_probe_health_when_service_was_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    actions, _ = mock_service_layer(monkeypatch, tx, active=False, enabled=False)
    health_called = False

    def health(_url: str, _timeout: float) -> dict[str, Any]:
        nonlocal health_called
        health_called = True
        return {}

    monkeypatch.setattr(tx, "wait_for_health", health)
    result = tx.apply_transaction(make_args(staged, live, state_root))

    assert result["service"]["restarted"] is False
    assert result["health"] == {"checked": False, "ok": True}
    assert actions == []
    assert health_called is False


def test_sha_mismatch_fails_before_service_queries_or_live_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    monkeypatch.setattr(
        tx,
        "systemctl_path",
        lambda: pytest.fail("service lookup must not happen on hash mismatch"),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root, expected="0" * 64))

    assert raised.value.code == "staged_hash_mismatch"
    assert live.read_bytes() == original
    assert not list(state_root.glob("transaction-*"))


def test_preexisting_state_root_must_already_be_private_and_is_not_chmodded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    state_root.mkdir(mode=0o755)
    state_root.chmod(0o755)
    mock_service_layer(monkeypatch, tx)
    monkeypatch.setattr(
        tx,
        "systemctl_path",
        lambda: pytest.fail("service lookup must not happen for an unsafe state root"),
    )

    with pytest.raises(tx.TransactionError, match="0700"):
        tx.apply_transaction(make_args(staged, live, state_root))

    assert stat.S_IMODE(state_root.stat().st_mode) == 0o755


def test_state_root_cannot_be_an_ancestor_of_live_or_staged_config(
    tmp_path: Path, tx: ModuleType
) -> None:
    staged, live, _ = prepare_files(tmp_path)
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, tmp_path.resolve()))
    assert raised.value.code == "invalid_path"


def test_restart_failure_automatically_restores_config_service_and_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    restart_count = 0

    def action(_systemctl: str, name: str, _service: str) -> None:
        nonlocal restart_count
        actions.append(name)
        if name == "restart":
            restart_count += 1
            if restart_count == 1:
                raise tx.TransactionError(
                    "service_action_failed", "service restart failed"
                )

    monkeypatch.setattr(tx, "service_action", action)

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "service_action_failed"
    assert raised.value.rollback["ok"] is True
    assert live.read_bytes() == original
    assert actions == ["restart", "daemon-reload", "enable", "restart"]
    assert raised.value.rollback["health"]["ok"] is True


def test_post_rename_file_operation_failure_still_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    real_atomic_install = tx.atomic_install
    calls = 0

    def fail_after_first_rename(
        path: Path,
        payload: bytes,
        *,
        uid: int,
        gid: int,
        mode: int,
        xattrs: dict[str, bytes] | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        real_atomic_install(path, payload, uid=uid, gid=gid, mode=mode, xattrs=xattrs)
        if calls == 1:
            raise tx.TransactionError(
                "fsync_failed", "transaction directory cannot be synchronized"
            )

    monkeypatch.setattr(tx, "atomic_install", fail_after_first_rename)

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "fsync_failed"
    assert raised.value.rollback["ok"] is True
    assert calls == 2
    assert live.read_bytes() == original


def test_partial_install_failure_automatic_rollback_bypasses_explicit_drift_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    real_atomic_install = tx.atomic_install
    calls = 0

    def partial_then_restore(
        path: Path,
        payload: bytes,
        *,
        uid: int,
        gid: int,
        mode: int,
        xattrs: dict[str, bytes] | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            path.write_bytes(b"partial install that is neither staged nor backup\n")
            raise tx.TransactionError("install_failed", "live config install failed")
        real_atomic_install(path, payload, uid=uid, gid=gid, mode=mode, xattrs=xattrs)

    monkeypatch.setattr(tx, "atomic_install", partial_then_restore)

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "install_failed"
    assert raised.value.rollback["ok"] is True
    assert calls == 2
    assert live.read_bytes() == original


def test_durable_recovery_before_rename_blocks_new_apply_until_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    class SimulatedKill(BaseException):
        pass

    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    real_restore = tx.restore_from_document
    triggered = False

    def kill_before_rename(phase: str) -> None:
        nonlocal triggered
        if phase == "apply_install_pending" and not triggered:
            triggered = True
            raise SimulatedKill()

    monkeypatch.setattr(tx, "after_checkpoint", kill_before_rename)
    monkeypatch.setattr(
        tx,
        "restore_from_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SimulatedKill()),
    )
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "apply_failed"
    assert raised.value.rollback == {"attempted": True, "ok": False}
    assert live.read_bytes() == original
    manifest = raised.value.manifest_path

    with pytest.raises(tx.TransactionError) as blocked:
        tx.apply_transaction(make_args(staged, live, state_root))
    assert blocked.value.code == "recovery_required"

    monkeypatch.setattr(tx, "after_checkpoint", lambda _phase: None)
    monkeypatch.setattr(tx, "restore_from_document", real_restore)
    recovered = tx.restore_transaction(argparse.Namespace(manifest=manifest))
    assert recovered["ok"] is True
    assert live.read_bytes() == original


def test_durable_recovery_after_rename_accepts_staged_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    class SimulatedKill(BaseException):
        pass

    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    real_atomic_install = tx.atomic_install
    real_restore = tx.restore_from_document
    calls = 0

    def kill_after_rename(
        path: Path,
        payload: bytes,
        *,
        uid: int,
        gid: int,
        mode: int,
        xattrs: dict[str, bytes] | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        real_atomic_install(path, payload, uid=uid, gid=gid, mode=mode, xattrs=xattrs)
        if calls == 1:
            raise SimulatedKill()

    monkeypatch.setattr(tx, "atomic_install", kill_after_rename)
    monkeypatch.setattr(
        tx,
        "restore_from_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SimulatedKill()),
    )
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.rollback == {"attempted": True, "ok": False}
    assert live.read_bytes() == staged.read_bytes()
    monkeypatch.setattr(tx, "atomic_install", real_atomic_install)
    monkeypatch.setattr(tx, "restore_from_document", real_restore)
    recovered = tx.restore_transaction(
        argparse.Namespace(manifest=raised.value.manifest_path)
    )
    assert recovered["ok"] is True
    assert live.read_bytes() == original


def test_durable_recovery_after_restart_resumes_without_new_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    class SimulatedKill(BaseException):
        pass

    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    real_restore = tx.restore_from_document
    restart_calls = 0

    def kill_after_restart(_systemctl: str, action: str, _service: str) -> None:
        nonlocal restart_calls
        actions.append(action)
        if action == "restart":
            restart_calls += 1
            if restart_calls == 1:
                raise SimulatedKill()

    monkeypatch.setattr(tx, "service_action", kill_after_restart)
    monkeypatch.setattr(
        tx,
        "restore_from_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SimulatedKill()),
    )
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert live.read_bytes() == staged.read_bytes()
    assert load_journal({"manifest": raised.value.manifest_path})["phase"] == (
        "apply_restart_pending"
    )
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda _systemctl, action, _service: actions.append(action),
    )
    monkeypatch.setattr(tx, "restore_from_document", real_restore)
    recovered = tx.restore_transaction(
        argparse.Namespace(manifest=raised.value.manifest_path)
    )
    assert recovered["ok"] is True
    assert live.read_bytes() == original


def test_new_generation_supersedes_terminal_generation_and_old_restore_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    first = tx.apply_transaction(make_args(staged, live, state_root))
    staged.write_bytes(b"receivers:\n  otlp:\n    protocols: {}\n")
    second = tx.apply_transaction(make_args(staged, live, state_root))

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=first["manifest"]))
    assert raised.value.code == "stale_transaction"

    restored = tx.restore_transaction(argparse.Namespace(manifest=second["manifest"]))
    assert restored["ok"] is True
    assert first["generation"] != second["generation"]


def test_failed_new_health_then_failed_rollback_health_is_reported_without_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)

    def failed_health(_url: str, _timeout: float) -> dict[str, Any]:
        raise tx.TransactionError("health_failed", "health verification failed")

    monkeypatch.setattr(tx, "wait_for_health", failed_health)

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "health_failed"
    assert raised.value.rollback == {"attempted": True, "ok": False}
    assert live.read_bytes() == original
    assert "url" not in json.dumps(raised.value.rollback)


def test_restore_reinstalls_exact_backup_metadata_and_prior_service_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    original_stat = live.stat()
    mock_service_layer(monkeypatch, tx, active=True, enabled=False)
    applied = tx.apply_transaction(make_args(staged, live, state_root))

    live.chmod(0o600)
    restore_actions: list[str] = []
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda _systemctl, action, _service: restore_actions.append(action),
    )
    restored = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert restored["ok"] is True
    assert live.read_bytes() == original
    current = live.stat()
    assert stat.S_IMODE(current.st_mode) == 0o640
    assert (current.st_uid, current.st_gid) == (
        original_stat.st_uid,
        original_stat.st_gid,
    )
    assert restore_actions == ["daemon-reload", "disable", "restart"]
    assert restored["health"]["ok"] is True


def test_explicit_restore_is_idempotent_when_live_already_matches_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    applied = tx.apply_transaction(make_args(staged, live, state_root))

    first = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    actions_after_first = list(actions)
    second = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert first["ok"] is True
    assert second["ok"] is True
    assert live.read_bytes() == original
    assert actions == actions_after_first
    assert load_journal(applied)["phase"] == "restored"


@pytest.mark.parametrize(
    "checkpoint_phase",
    [
        "restore_daemon_reload_done",
        "restore_enablement_done",
        "restore_active_done",
        "restored",
    ],
)
def test_restore_resumes_after_failure_following_each_action_or_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    checkpoint_phase: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    injected = False

    def interrupt_after_checkpoint(phase: str) -> None:
        nonlocal injected
        if phase == checkpoint_phase and not injected:
            injected = True
            raise tx.TransactionError(
                "injected_failure", "injected transaction failure"
            )

    monkeypatch.setattr(tx, "after_checkpoint", interrupt_after_checkpoint)
    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert raised.value.code == "injected_failure"

    result = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert result["ok"] is True
    assert live.read_bytes() == original
    assert load_journal(applied)["phase"] == "restored"


@pytest.mark.parametrize(
    "failure_after", ["daemon-reload", "enable", "restart", "health"]
)
def test_restore_retries_when_failure_occurs_after_side_effect_before_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    failure_after: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    injected = False

    def action(_systemctl: str, name: str, _service: str) -> None:
        nonlocal injected
        actions.append(name)
        if name == failure_after and not injected:
            injected = True
            raise tx.TransactionError(
                "injected_failure", "injected transaction failure"
            )

    real_health = tx.wait_for_health

    def health(url: str, timeout: float) -> dict[str, Any]:
        nonlocal injected
        result = real_health(url, timeout)
        if failure_after == "health" and not injected:
            injected = True
            raise tx.TransactionError(
                "injected_failure", "injected transaction failure"
            )
        return result

    monkeypatch.setattr(tx, "service_action", action)
    monkeypatch.setattr(tx, "wait_for_health", health)
    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert raised.value.code == "injected_failure"

    result = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert result["ok"] is True
    assert live.read_bytes() == original


def test_explicit_restore_rejects_unrelated_live_config_drift_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    drifted = b"unrelated: operator change\n"
    live.write_bytes(drifted)
    actions: list[str] = []
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda _systemctl, action, _service: actions.append(action),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert raised.value.code == "live_config_drift"
    assert live.read_bytes() == drifted
    assert actions == []


def test_explicit_restore_requires_exact_loaded_systemd_unit_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda *_args: {"id": "different.service", "load_state": "loaded"},
    )
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda *_args: pytest.fail(
            "service action must not run for an unresolved unit"
        ),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert raised.value.code == "recovery_required"
    assert raised.value.rollback["config_restored"] is True
    assert live.read_bytes() == original


@pytest.mark.parametrize(
    ("drift", "error_code"),
    [
        ("host", "host_drift"),
        ("packages", "recovery_required"),
        ("binary", "recovery_required"),
        ("unit", "recovery_required"),
    ],
)
def test_restore_fails_closed_on_host_package_binary_or_unit_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    drift: str,
    error_code: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    installed = live.read_bytes()

    if drift == "host":
        monkeypatch.setattr(tx, "host_fingerprint", lambda: "4" * 64)
    elif drift == "packages":
        monkeypatch.setattr(
            tx,
            "package_versions",
            lambda: {
                "lemonade-server": "10.10.1",
                "splunk-otel-collector": "0.156.0",
            },
        )
    elif drift == "binary":
        monkeypatch.setattr(
            tx,
            "collector_binary_provenance",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                tx.TransactionError(
                    "collector_binary_drift",
                    "collector binary path or SHA-256 cannot be verified",
                )
            ),
        )
    else:
        monkeypatch.setattr(tx, "service_unit_fingerprint", lambda *_args: "4" * 64)

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert raised.value.code == error_code
    if drift == "host":
        assert live.read_bytes() == installed
    else:
        assert live.read_bytes() == original
        assert raised.value.rollback["config_restored"] is True


def test_apply_revalidates_unit_fingerprint_before_live_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    calls = 0

    def changing_fingerprint(*_args: Any) -> str:
        nonlocal calls
        calls += 1
        return "2" * 64 if calls == 1 else "4" * 64

    monkeypatch.setattr(tx, "service_unit_fingerprint", changing_fingerprint)
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "recovery_required"
    assert raised.value.rollback["config_restored"] is True
    assert live.read_bytes() == original


def test_restore_revalidates_unit_fingerprint_at_config_mutation_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    calls = 0

    def changing_fingerprint(*_args: Any) -> str:
        nonlocal calls
        calls += 1
        return "2" * 64 if calls == 1 else "4" * 64

    monkeypatch.setattr(tx, "service_unit_fingerprint", changing_fingerprint)
    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert raised.value.code == "recovery_required"
    assert live.read_bytes() == original


@pytest.mark.parametrize(
    "boundary",
    [
        "before_install",
        "before_restart",
        "after_restart",
        "before_health",
        "after_health",
        "before_applied",
    ],
)
@pytest.mark.parametrize("provenance_kind", ["packages", "binary", "unit"])
def test_apply_provenance_race_at_every_boundary_restores_only_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    boundary: str,
    provenance_kind: str,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    drifted = False

    def inject_drift(current_boundary: str) -> None:
        nonlocal drifted
        if current_boundary == boundary:
            drifted = True

    monkeypatch.setattr(tx, "before_provenance_check", inject_drift)
    if provenance_kind == "packages":
        monkeypatch.setattr(
            tx,
            "package_versions",
            lambda: {
                "lemonade-server": "10.10.1" if drifted else "10.10.0",
                "splunk-otel-collector": "0.156.0",
            },
        )
    elif provenance_kind == "binary":

        def binary(path: Path, expected: str, **_kwargs: Any) -> dict[str, Any]:
            if drifted:
                raise tx.TransactionError(
                    "collector_binary_drift",
                    "collector binary path or SHA-256 cannot be verified",
                )
            return {
                "path": str(path),
                "sha256": expected,
                "device": 1,
                "inode": 2,
            }

        monkeypatch.setattr(tx, "collector_binary_provenance", binary)
    else:
        monkeypatch.setattr(
            tx,
            "service_unit_fingerprint",
            lambda *_args: ("4" if drifted else "2") * 64,
        )

    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "recovery_required"
    assert raised.value.rollback == {
        "attempted": True,
        "ok": False,
        "config_restored": True,
        "service_state_restored": False,
        "recovery_required": True,
    }
    assert live.read_bytes() == original
    assert load_journal({"manifest": raised.value.manifest_path})["phase"] == (
        "recovery_required"
    )
    assert all(action == "restart" for action in actions)


def test_recovery_required_generation_resumes_after_runtime_is_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    drifted = False

    def inject(boundary: str) -> None:
        nonlocal drifted
        if boundary == "before_restart":
            drifted = True

    monkeypatch.setattr(tx, "before_provenance_check", inject)
    monkeypatch.setattr(
        tx,
        "package_versions",
        lambda: {
            "lemonade-server": "10.10.1" if drifted else "10.10.0",
            "splunk-otel-collector": "0.156.0",
        },
    )
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))
    assert raised.value.code == "recovery_required"
    assert live.read_bytes() == original

    drifted = False
    monkeypatch.setattr(tx, "before_provenance_check", lambda _boundary: None)
    restored = tx.restore_transaction(
        argparse.Namespace(manifest=raised.value.manifest_path)
    )
    assert restored["ok"] is True
    assert load_journal({"manifest": raised.value.manifest_path})["phase"] == "restored"


@pytest.mark.parametrize(
    ("drift_field", "active", "enabled"),
    [("active", False, True), ("unit", True, False)],
)
def test_terminal_restore_proves_exact_active_and_unit_file_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tx: ModuleType,
    drift_field: str,
    active: bool,
    enabled: bool,
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx, active=True, enabled=True)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    monkeypatch.setattr(
        tx,
        "service_metadata",
        lambda *_args: {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": "active" if active else "inactive",
            "unit_file_state": "enabled" if enabled else "disabled",
        },
    )
    monkeypatch.setattr(
        tx,
        "service_boolean",
        lambda _systemctl, operation, _service: (
            active
            if operation == "is-active"
            else pytest.fail("is-enabled must not be used")
        ),
    )

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))
    assert drift_field in {"active", "unit"}
    assert raised.value.code == "recovery_required"


def test_restore_rejects_unit_file_state_false_success_after_disable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    actions, _ = mock_service_layer(monkeypatch, tx, active=True, enabled=False)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    disable_ran = False

    def metadata(*_args: Any) -> dict[str, str]:
        return {
            "id": "splunk-otel-collector.service",
            "load_state": "loaded",
            "active_state": "active",
            "unit_file_state": "enabled" if disable_ran else "disabled",
        }

    def action(_systemctl: str, name: str, _service: str) -> None:
        nonlocal disable_ran
        actions.append(name)
        if name == "disable":
            disable_ran = True

    monkeypatch.setattr(tx, "service_metadata", metadata)
    monkeypatch.setattr(tx, "service_action", action)
    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert raised.value.code == "recovery_required"
    assert "restart" not in actions[1:]


def test_restore_inactive_state_stops_without_health_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx, active=False, enabled=True)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    actions: list[str] = []
    monkeypatch.setattr(
        tx,
        "service_action",
        lambda _systemctl, action, _service: actions.append(action),
    )
    monkeypatch.setattr(
        tx,
        "wait_for_health",
        lambda *_args: pytest.fail("inactive restore must not probe health"),
    )

    result = tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert actions == ["daemon-reload", "enable", "stop"]
    assert result["health"] == {"checked": False, "ok": True}


def test_restore_rejects_tampered_backup_before_live_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    installed = live.read_bytes()
    manifest = json.loads(Path(applied["manifest"]).read_text(encoding="utf-8"))
    backup = Path(manifest["backup_path"])
    backup.write_bytes(b"tampered")
    backup.chmod(0o600)

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=applied["manifest"]))

    assert raised.value.code == "backup_hash_mismatch"
    assert live.read_bytes() == installed


def test_restore_rejects_backup_path_escape_and_manifest_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    manifest_path = Path(applied["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["backup_path"] = str(tmp_path.resolve() / "outside.backup")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)

    with pytest.raises(tx.TransactionError) as raised:
        tx.restore_transaction(argparse.Namespace(manifest=str(manifest_path)))
    assert raised.value.code == "invalid_manifest"

    real_manifest = tmp_path.resolve() / "real-manifest.json"
    real_manifest.write_text("{}", encoding="utf-8")
    link = tmp_path.resolve() / "manifest-link.json"
    link.symlink_to(real_manifest)
    with pytest.raises(tx.TransactionError, match="symbolic link"):
        tx.load_manifest(link)


def test_restore_requires_private_manifest_and_backup_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    staged, live, state_root = prepare_files(tmp_path)
    mock_service_layer(monkeypatch, tx)
    applied = tx.apply_transaction(make_args(staged, live, state_root))
    manifest_path = Path(applied["manifest"])
    manifest_path.chmod(0o640)
    with pytest.raises(tx.TransactionError, match="0600"):
        tx.restore_transaction(argparse.Namespace(manifest=str(manifest_path)))


def test_wait_for_health_does_not_read_or_reflect_body(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    class Response:
        def getcode(self) -> int:
            return 204

        def read(self, *_args: Any) -> bytes:
            raise AssertionError("health response body must never be read")

        def close(self) -> None:
            pass

    class Opener:
        def open(self, request: Any, *, timeout: float) -> Response:
            assert request.full_url == "http://127.0.0.1:13133/"
            assert 0 < timeout <= 2.0
            return Response()

    monkeypatch.setattr(tx, "build_health_opener", lambda: Opener())
    result = tx.wait_for_health("http://127.0.0.1:13133/", 1.0)
    assert result == {"checked": True, "ok": True, "status_code": 204}


def test_redirect_is_rejected_without_reflecting_location(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    secret_location = "http://127.0.0.1:13133/?secret=do-not-reflect"

    class Opener:
        def open(self, *_args: Any, **_kwargs: Any) -> Any:
            raise tx.TransactionError(
                "health_redirect", "health endpoint redirects are not allowed"
            )

    monkeypatch.setattr(tx, "build_health_opener", lambda: Opener())
    with pytest.raises(tx.TransactionError) as raised:
        tx.wait_for_health("http://127.0.0.1:13133/", 1.0)
    assert secret_location not in raised.value.safe_message


def test_local_command_never_uses_shell_and_drops_inherited_environment(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(
        arguments: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setenv("SPLUNK_ACCESS_TOKEN", "must-not-be-inherited")
    monkeypatch.setattr(tx.subprocess, "run", fake_run)
    tx.run_command(["/usr/bin/systemctl", "show", "service"])

    assert isinstance(captured["arguments"], list)
    assert "shell" not in captured
    assert "SPLUNK_ACCESS_TOKEN" not in captured["env"]
    assert captured["env"] == tx.SUBPROCESS_ENV


def test_service_inventory_uses_show_allowlist_not_cat_or_environment(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    commands: list[list[str]] = []

    def fake_command(arguments: list[str] | tuple[str, ...], **_kwargs: Any) -> Any:
        commands.append(list(arguments))
        return subprocess.CompletedProcess(
            arguments,
            0,
            "Id=splunk-otel-collector.service\nEnvironment=TOKEN=secret\nLoadState=loaded\n",
            "",
        )

    monkeypatch.setattr(tx, "run_command", fake_command)
    metadata = tx.service_metadata("/usr/bin/systemctl", "collector.service")
    command = " ".join(commands[0])
    assert " show " in f" {command} "
    assert " cat " not in f" {command} "
    assert "Environment" not in commands[0][2]
    assert metadata == {"id": "splunk-otel-collector.service", "load_state": "loaded"}


def test_unit_fingerprint_hashes_fragment_and_dropins_without_recording_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    fragment = tmp_path.resolve() / "collector.service"
    dropin = tmp_path.resolve() / "10-runtime.conf"
    fragment.write_text("[Service]\nExecStart=/usr/bin/otelcol\n", encoding="utf-8")
    dropin.write_text("[Service]\nEnvironmentFile=/protected/path\n", encoding="utf-8")
    monkeypatch.setattr(
        tx, "assert_root_owned_secure_path", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        tx,
        "run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            f"FragmentPath={fragment}\nDropInPaths={dropin}\n",
            "",
        ),
    )

    first = tx.service_unit_fingerprint("/usr/bin/systemctl", "collector.service")
    dropin.write_text("[Service]\nEnvironmentFile=/another/path\n", encoding="utf-8")
    second = tx.service_unit_fingerprint("/usr/bin/systemctl", "collector.service")

    assert len(first) == 64
    assert first != second
    assert "protected" not in first
    assert "another" not in second


def test_collector_binary_requires_exact_sha_secure_mode_and_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    binary = tmp_path.resolve() / "otelcol"
    binary.write_bytes(b"collector-binary")
    binary.chmod(0o755)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(
        tx, "assert_root_owned_secure_path", lambda *_args, **_kwargs: None
    )

    provenance = tx.collector_binary_provenance(binary, expected)
    assert provenance["path"] == str(binary)
    assert provenance["sha256"] == expected
    assert isinstance(provenance["device"], int)
    assert isinstance(provenance["inode"], int)
    with pytest.raises(tx.TransactionError) as raised:
        tx.collector_binary_provenance(binary, "0" * 64)
    assert raised.value.code == "collector_binary_drift"

    binary.chmod(0o775)
    with pytest.raises(tx.TransactionError):
        tx.collector_binary_provenance(binary, expected)
    binary.chmod(0o644)
    with pytest.raises(tx.TransactionError):
        tx.collector_binary_provenance(binary, expected)


def test_collector_binary_rejects_same_hash_replaced_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    binary = tmp_path.resolve() / "otelcol"
    binary.write_bytes(b"collector-binary")
    binary.chmod(0o755)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    monkeypatch.setattr(
        tx, "assert_root_owned_secure_path", lambda *_args, **_kwargs: None
    )
    first = tx.collector_binary_provenance(binary, expected)
    replacement = tmp_path.resolve() / "otelcol.new"
    replacement.write_bytes(binary.read_bytes())
    replacement.chmod(0o755)
    replacement.replace(binary)

    with pytest.raises(tx.TransactionError) as raised:
        tx.collector_binary_provenance(
            binary,
            expected,
            expected_device=first["device"],
            expected_inode=first["inode"],
        )
    assert raised.value.code == "collector_binary_drift"


def test_package_inventory_requires_every_exact_allowlisted_package(
    tx: ModuleType,
) -> None:
    with pytest.raises(tx.TransactionError) as raised:
        tx.validated_package_versions({"splunk-otel-collector": "0.156.0"})
    assert raised.value.code == "package_inventory_failed"


def test_signal_handler_raises_sanitized_transaction_error(tx: ModuleType) -> None:
    with pytest.raises(tx.TransactionError) as raised:
        tx._transaction_signal_handler(15, None)
    assert raised.value.code == "interrupted"


def test_apply_catches_baseexception_and_attempts_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    class FatalInterruption(BaseException):
        pass

    staged, live, state_root = prepare_files(tmp_path)
    original = live.read_bytes()
    mock_service_layer(monkeypatch, tx)
    real_atomic_install = tx.atomic_install
    calls = 0

    def interrupt_after_install(
        path: Path,
        payload: bytes,
        *,
        uid: int,
        gid: int,
        mode: int,
        xattrs: dict[str, bytes] | None = None,
    ) -> None:
        nonlocal calls
        calls += 1
        real_atomic_install(path, payload, uid=uid, gid=gid, mode=mode, xattrs=xattrs)
        if calls == 1:
            raise FatalInterruption()

    monkeypatch.setattr(tx, "atomic_install", interrupt_after_install)
    with pytest.raises(tx.TransactionError) as raised:
        tx.apply_transaction(make_args(staged, live, state_root))

    assert raised.value.code == "apply_failed"
    assert raised.value.rollback["ok"] is True
    assert live.read_bytes() == original


def test_runtime_requires_linux_and_root(
    monkeypatch: pytest.MonkeyPatch, tx: ModuleType
) -> None:
    monkeypatch.setattr(tx.sys, "platform", "darwin")
    with pytest.raises(tx.TransactionError) as raised:
        tx.validate_runtime()
    assert raised.value.code == "unsupported_platform"

    monkeypatch.setattr(tx.sys, "platform", "linux")
    monkeypatch.setattr(tx.os, "geteuid", lambda: 1000)
    with pytest.raises(tx.TransactionError) as raised:
        tx.validate_runtime()
    assert raised.value.code == "root_required"


def test_main_emits_sanitized_json_for_argument_and_internal_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tx: ModuleType
) -> None:
    assert tx.main(["apply", "--staged", "secret-value"]) == 1
    argument_error = json.loads(capsys.readouterr().err)
    assert argument_error == {
        "ok": False,
        "operation": "unknown",
        "error": {
            "code": "invalid_arguments",
            "message": "command arguments are invalid",
        },
    }
    assert "secret-value" not in json.dumps(argument_error)

    monkeypatch.setattr(tx, "validate_runtime", lambda: None)
    monkeypatch.setattr(
        tx,
        "restore_transaction",
        lambda _args: (_ for _ in ()).throw(RuntimeError("TOKEN=do-not-reflect")),
    )
    assert tx.main(["restore", "--manifest", "/safe/path"]) == 1
    internal_error = json.loads(capsys.readouterr().err)
    assert internal_error["error"]["code"] == "internal_error"
    assert "do-not-reflect" not in json.dumps(internal_error)


def test_apply_failure_json_reports_rollback_without_subprocess_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tx: ModuleType
) -> None:
    failure = tx.TransactionError("health_failed", "health verification failed")
    failure.rollback = {"attempted": True, "ok": True}
    failure.manifest_path = "/var/lib/lemonade-otel/transaction-a/manifest.json"
    monkeypatch.setattr(tx, "validate_runtime", lambda: None)
    monkeypatch.setattr(
        tx,
        "apply_transaction",
        lambda _args: (_ for _ in ()).throw(failure),
    )

    argv = [
        "apply",
        "--staged",
        "/staged",
        "--live",
        "/live",
        "--service",
        "collector.service",
        "--health-url",
        "http://127.0.0.1:1/",
        "--expected-sha256",
        "0" * 64,
        "--collector-binary",
        "/usr/bin/otelcol",
        "--collector-binary-sha256",
        "1" * 64,
        "--state-root",
        "/state",
    ]
    assert tx.main(argv) == 1
    output = json.loads(capsys.readouterr().err)
    assert output["rollback"] == {"attempted": True, "ok": True}
    assert output["error"] == {
        "code": "health_failed",
        "message": "health verification failed",
    }


def test_recovery_required_json_is_sanitized_and_actionable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tx: ModuleType
) -> None:
    failure = tx.TransactionError(
        "recovery_required",
        "verified config bytes were restored; runtime recovery is required",
    )
    failure.cause_code = "package_version_drift:SECRET=must-not-reflect"
    failure.manifest_path = "/var/lib/lemonade-otel/transaction-a/manifest.json"
    failure.rollback = {
        "attempted": True,
        "ok": False,
        "config_restored": True,
        "service_state_restored": False,
        "recovery_required": True,
    }
    monkeypatch.setattr(tx, "validate_runtime", lambda: None)
    monkeypatch.setattr(
        tx,
        "apply_transaction",
        lambda _args: (_ for _ in ()).throw(failure),
    )
    argv = [
        "apply",
        "--staged",
        "/staged",
        "--live",
        "/live",
        "--service",
        "collector.service",
        "--health-url",
        "http://127.0.0.1:1/",
        "--expected-sha256",
        "0" * 64,
        "--collector-binary",
        "/usr/bin/otelcol",
        "--collector-binary-sha256",
        "1" * 64,
        "--state-root",
        "/state",
    ]

    assert tx.main(argv) == 1
    output = json.loads(capsys.readouterr().err)
    assert output["error"]["code"] == "recovery_required"
    assert output["rollback"]["config_restored"] is True
    assert "must-not-reflect" not in json.dumps(output)


def test_script_is_executable_and_cli_output_is_json_on_this_nonlinux_host() -> None:
    assert os.access(SCRIPT, os.X_OK), "transaction helper must be executable"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "restore", "--manifest", "/missing"],
        check=False,
        capture_output=True,
        text=True,
    )
    # On Linux CI this is root/platform dependent, but either path must retain
    # the JSON-only contract and fail before touching the requested manifest.
    assert result.returncode != 0
    output = json.loads(result.stderr)
    assert output["ok"] is False
    assert isinstance(output["error"]["code"], str)

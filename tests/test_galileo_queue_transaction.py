from __future__ import annotations

import copy
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "skills"
    / "galileo-lemonade-instrumentation-setup"
    / "scripts"
    / "transactional_queue_directory.py"
)
FINGERPRINT = "a" * 64
VERSION = "0.156.0"
SERVICE = "splunk-otel-collector.service"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "galileo_transactional_queue_directory", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tx() -> ModuleType:
    return load_module()


def directory_record(path: Path) -> dict[str, int]:
    info = path.stat()
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
    }


class FakeSystem:
    def __init__(self, provenance: dict[str, Any]) -> None:
        self.provenance = copy.deepcopy(provenance)
        self.drift = False
        self.verify_calls = 0

    def capture(self, service: str, expected_version: str) -> dict[str, Any]:
        assert service == SERVICE
        assert expected_version == VERSION
        return copy.deepcopy(self.provenance)

    def verify(self, expected: dict[str, Any]) -> None:
        self.verify_calls += 1
        if self.drift or expected != self.provenance:
            raise RuntimeError("sensitive fake provenance detail")


def make_case(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    uid = os.geteuid()
    gid = os.getegid()
    private = tmp_path.resolve() / "private"
    queue_root = private / "var/lib/splunk-otel-collector/galileo-queue"
    quarantine_root = private / "var/lib/splunk-otel-collector/galileo-queue-quarantine"
    state_root = private / "var/lib/galileo-queue-transactions"
    for path in (queue_root, quarantine_root, state_root.parent):
        path.mkdir(parents=True, exist_ok=True)
    for path in [private, *private.rglob("*")]:
        if path.is_dir():
            path.chmod(0o700)
    queue_root.chmod(0o750)
    quarantine_root.chmod(0o700)
    monkeypatch.setattr(tx, "QUEUE_ROOT", queue_root)
    monkeypatch.setattr(tx, "QUARANTINE_ROOT", quarantine_root)
    monkeypatch.setattr(tx, "STATE_ROOT", state_root)
    provenance = {
        "machine_fingerprint": "1" * 64,
        "package": {"name": tx.PACKAGE_NAME, "version": VERSION},
        "service": {
            "name": SERVICE,
            "user": "collector-test",
            "group": "collector-test",
            "uid": uid,
            "gid": gid,
            "active_state": "active",
            "unit_file_state": "enabled",
            "unit_fingerprint": "2" * 64,
        },
        "queue_root": directory_record(queue_root),
        "quarantine_root": directory_record(quarantine_root),
    }
    return {
        "uid": uid,
        "gid": gid,
        "queue_root": queue_root,
        "quarantine_root": quarantine_root,
        "state_root": state_root,
        "system": FakeSystem(provenance),
    }


def apply(tx: ModuleType, case: dict[str, Any]) -> dict[str, Any]:
    return tx.apply_queue(
        fingerprint=FINGERPRINT,
        service=SERVICE,
        expected_package_version=VERSION,
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )


def manifest_path(case: dict[str, Any], result: dict[str, Any]) -> Path:
    return case["state_root"] / f"generation-{result['generation']}" / "manifest.json"


def restore(
    tx: ModuleType, case: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    return tx.restore_queue(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )


def test_apply_creates_exact_destination_bound_private_queue(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    info = target.stat()
    assert result == {
        "ok": True,
        "operation": "apply",
        "status": "applied",
        "generation": result["generation"],
        "fingerprint": FINGERPRINT,
    }
    assert stat.S_ISDIR(info.st_mode)
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (
        case["uid"],
        case["gid"],
        0o700,
    )
    current = json.loads((case["state_root"] / "current.json").read_text())
    assert current["generation"] == result["generation"]
    journal = json.loads(
        (
            case["state_root"] / f"generation-{result['generation']}" / "journal.json"
        ).read_text()
    )
    assert journal["phase"] == "applied"
    assert journal["created_queue"] == {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": 0o700,
        "ctime_ns": info.st_ctime_ns,
        "fingerprint": FINGERPRINT,
    }


def test_restore_removes_only_the_exact_empty_created_queue_and_is_idempotent(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    restored = restore(tx, case, result)
    assert restored["disposition"] == "removed"
    assert not (case["queue_root"] / FINGERPRINT).exists()
    assert not (case["state_root"] / "current.json").exists()
    assert restore(tx, case, result)["disposition"] == "removed"


def test_completed_restore_rechecks_active_path_before_claiming_idempotence(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    assert restore(tx, case, result)["disposition"] == "removed"
    recreated = case["queue_root"] / FINGERPRINT
    recreated.mkdir(mode=0o700)
    with pytest.raises(tx.TransactionError) as exc_info:
        restore(tx, case, result)
    assert exc_info.value.code == "restored_state_drift"
    assert recreated.is_dir()


def test_nonempty_queue_is_atomically_quarantined_and_content_is_preserved(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    (target / ".hidden-database").write_bytes(b"opaque queued data")
    restored = restore(tx, case, result)
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    assert restored["disposition"] == "quarantined"
    assert not target.exists()
    assert (quarantine / ".hidden-database").read_bytes() == b"opaque queued data"
    info = quarantine.stat()
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (
        case["uid"],
        case["gid"],
        0o700,
    )


def test_completed_quarantine_restore_rechecks_recorded_inode_and_metadata(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    (target / "queue.db").write_bytes(b"preserve")
    assert restore(tx, case, result)["disposition"] == "quarantined"
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    quarantine.chmod(0o750)
    with pytest.raises(tx.TransactionError) as exc_info:
        restore(tx, case, result)
    assert exc_info.value.code == "restored_state_drift"
    assert (quarantine / "queue.db").read_bytes() == b"preserve"


@pytest.mark.parametrize("drift", ["mode", "inode"])
def test_drifted_empty_queue_is_quarantined_never_deleted(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    if drift == "mode":
        target.chmod(0o750)
    else:
        target.rmdir()
        target.mkdir(mode=0o700)
    restored = restore(tx, case, result)
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    assert restored["disposition"] == "quarantined"
    assert quarantine.is_dir()
    assert not target.exists()


def test_regular_file_replacement_is_quarantined_without_reading_or_deleting_it(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    target.rmdir()
    target.write_bytes(b"opaque replacement")
    target.chmod(0o644)
    restored = restore(tx, case, result)
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    assert restored["disposition"] == "quarantined"
    assert quarantine.read_bytes() == b"opaque replacement"
    assert stat.S_IMODE(quarantine.stat().st_mode) == 0o600


def test_uncertain_create_is_quarantined_because_generation_cannot_prove_identity(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)

    def crash(operation: str) -> None:
        if operation == "create":
            raise RuntimeError("simulated abrupt termination")

    monkeypatch.setattr(tx, "after_queue_side_effect", crash)
    with pytest.raises(tx.TransactionError) as exc_info:
        apply(tx, case)
    assert exc_info.value.rollback == {
        "attempted": True,
        "ok": True,
        "disposition": "quarantined",
    }
    generation = exc_info.value.generation
    assert not (case["queue_root"] / FINGERPRINT).exists()
    assert (
        case["quarantine_root"] / tx.quarantine_name(generation, FINGERPRINT)
    ).is_dir()


def test_restore_resumes_after_quarantine_rename_before_checkpoint(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    (target / "queue.db").write_bytes(b"preserve")

    def crash(operation: str) -> None:
        if operation == "quarantine":
            raise RuntimeError("simulated abrupt termination")

    monkeypatch.setattr(tx, "after_queue_side_effect", crash)
    with pytest.raises(tx.TransactionError):
        restore(tx, case, result)
    assert not target.exists()
    monkeypatch.setattr(tx, "after_queue_side_effect", lambda _operation: None)
    resumed = restore(tx, case, result)
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    assert resumed["disposition"] == "quarantined"
    assert (quarantine / "queue.db").read_bytes() == b"preserve"


def test_crash_after_empty_queue_retire_rename_preserves_it_conservatively(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)

    def crash(operation: str) -> None:
        if operation == "retire_rename":
            raise RuntimeError("simulated abrupt termination")

    monkeypatch.setattr(tx, "after_queue_side_effect", crash)
    with pytest.raises(tx.TransactionError):
        restore(tx, case, result)
    target = case["queue_root"] / FINGERPRINT
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    assert not target.exists()
    assert quarantine.is_dir()
    monkeypatch.setattr(tx, "after_queue_side_effect", lambda _operation: None)
    assert restore(tx, case, result)["disposition"] == "quarantined"
    assert quarantine.is_dir()


def test_crash_after_exact_empty_removal_resumes_as_already_absent(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)

    def crash(operation: str) -> None:
        if operation == "remove":
            raise RuntimeError("simulated abrupt termination")

    monkeypatch.setattr(tx, "after_queue_side_effect", crash)
    with pytest.raises(tx.TransactionError):
        restore(tx, case, result)
    assert not (case["queue_root"] / FINGERPRINT).exists()
    assert not (
        case["quarantine_root"] / tx.quarantine_name(result["generation"], FINGERPRINT)
    ).exists()
    monkeypatch.setattr(tx, "after_queue_side_effect", lambda _operation: None)
    assert restore(tx, case, result)["disposition"] == "already_absent"


def test_provenance_drift_stops_restore_without_touching_queue(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    case["system"].drift = True
    with pytest.raises(tx.TransactionError) as exc_info:
        restore(tx, case, result)
    assert exc_info.value.code == "restore_failed"
    assert "sensitive" not in exc_info.value.safe_message
    assert target.is_dir()
    journal = json.loads(
        (
            case["state_root"] / f"generation-{result['generation']}" / "journal.json"
        ).read_text()
    )
    assert journal["phase"] == "recovery_required"
    case["system"].drift = False
    assert restore(tx, case, result)["disposition"] == "removed"


def test_support_root_drift_stops_restore_until_exact_root_is_reconciled(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    case["quarantine_root"].chmod(0o750)
    with pytest.raises(tx.TransactionError) as exc_info:
        restore(tx, case, result)
    assert exc_info.value.code == "unsafe_directory"
    assert target.is_dir()
    case["quarantine_root"].chmod(0o700)
    assert restore(tx, case, result)["disposition"] == "removed"


@pytest.mark.parametrize("failure", ["private_mode", "wrong_service_group"])
def test_queue_root_must_use_a_documented_collector_traversable_shape(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    if failure == "private_mode":
        case["queue_root"].chmod(0o700)
        case["system"].provenance["queue_root"] = directory_record(case["queue_root"])
    else:
        case["system"].provenance["service"]["gid"] = case["gid"] + 1
    with pytest.raises(tx.TransactionError) as exc_info:
        apply(tx, case)
    assert exc_info.value.code == "invalid_state"
    assert not (case["queue_root"] / FINGERPRINT).exists()


def test_existing_destination_fails_before_generation_and_is_never_moved(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    target = case["queue_root"] / FINGERPRINT
    target.mkdir(mode=0o700)
    (target / "existing.db").write_bytes(b"existing")
    with pytest.raises(tx.TransactionError) as exc_info:
        apply(tx, case)
    assert exc_info.value.code == "queue_exists"
    assert (target / "existing.db").read_bytes() == b"existing"
    assert not case["state_root"].exists()


def test_current_generation_blocks_overlapping_apply(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_queue(
            fingerprint="b" * 64,
            service=SERVICE,
            expected_package_version=VERSION,
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "current_generation"
    restore(tx, case, result)


def test_reapply_uses_a_new_generation_without_reusing_old_quarantine(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    first = apply(tx, case)
    active = case["queue_root"] / FINGERPRINT
    (active / "queue.db").write_bytes(b"old destination-bound data")
    assert restore(tx, case, first)["disposition"] == "quarantined"
    old_quarantine = case["quarantine_root"] / tx.quarantine_name(
        first["generation"], FINGERPRINT
    )

    second = apply(tx, case)
    assert second["generation"] != first["generation"]
    assert active.is_dir()
    assert not any(active.iterdir())
    assert (old_quarantine / "queue.db").read_bytes() == b"old destination-bound data"
    assert restore(tx, case, second)["disposition"] == "removed"
    assert (old_quarantine / "queue.db").read_bytes() == b"old destination-bound data"


def test_quarantine_collision_preserves_both_entries_and_requires_recovery(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    target = case["queue_root"] / FINGERPRINT
    (target / "queue.db").write_bytes(b"source")
    quarantine = case["quarantine_root"] / tx.quarantine_name(
        result["generation"], FINGERPRINT
    )
    quarantine.mkdir(mode=0o700)
    (quarantine / "other.db").write_bytes(b"other")
    with pytest.raises(tx.TransactionError) as exc_info:
        restore(tx, case, result)
    assert exc_info.value.code == "quarantine_collision"
    assert (target / "queue.db").read_bytes() == b"source"
    assert (quarantine / "other.db").read_bytes() == b"other"


def test_support_root_symlink_is_rejected_before_state_or_queue_mutation(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    real = case["queue_root"]
    linked = real.parent / "linked-queue-root"
    linked.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(tx, "QUEUE_ROOT", linked)
    with pytest.raises(tx.TransactionError) as exc_info:
        apply(tx, case)
    assert exc_info.value.code == "unsafe_directory"
    assert not case["state_root"].exists()


def test_hardlinked_lock_is_rejected_without_modifying_linked_file(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["state_root"].mkdir(mode=0o700)
    victim = case["state_root"] / "victim"
    victim.write_bytes(b"preserve")
    victim.chmod(0o600)
    os.link(victim, case["state_root"] / ".transaction.lock")
    with pytest.raises(tx.TransactionError) as exc_info:
        apply(tx, case)
    assert exc_info.value.code == "lock_failed"
    assert victim.read_bytes() == b"preserve"
    assert victim.stat().st_nlink == 2


def test_checkpoint_hook_observes_durable_intent_and_current_pointer(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    observed: list[tuple[str, str | None]] = []

    def inspect_checkpoint(phase: str, intent: str | None) -> None:
        observed.append((phase, intent))
        if phase != "creating":
            return
        current = json.loads((case["state_root"] / "current.json").read_text())
        journal = json.loads(
            (
                case["state_root"]
                / f"generation-{current['generation']}"
                / "journal.json"
            ).read_text()
        )
        assert journal["phase"] == "creating"
        assert journal["intent"] == "create"

    monkeypatch.setattr(tx, "after_checkpoint", inspect_checkpoint)
    result = apply(tx, case)
    assert ("creating", "create") in observed
    restore(tx, case, result)


def test_manifest_copy_cannot_restore_current_generation(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = apply(tx, case)
    copied = case["state_root"] / "copied-manifest.json"
    copied.write_bytes(manifest_path(case, result).read_bytes())
    copied.chmod(0o600)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.restore_queue(
            copied,
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_state"
    restore(tx, case, result)


def test_cli_error_is_sanitized_and_does_not_echo_rejected_value(
    tx: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rejected = "secret/path/value"
    monkeypatch.setattr(tx, "validate_runtime", lambda: None)
    result = tx.main(
        [
            "apply",
            "--fingerprint",
            rejected,
            "--service",
            SERVICE,
            "--expected-package-version",
            VERSION,
        ]
    )
    captured = capsys.readouterr()
    assert result == 1
    assert rejected not in captured.out + captured.err
    document = json.loads(captured.err)
    assert document["error"]["code"] == "invalid_fingerprint"
    assert "path" not in captured.err.lower()

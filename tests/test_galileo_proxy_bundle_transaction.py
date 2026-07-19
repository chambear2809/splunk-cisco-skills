from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "galileo-lemonade-instrumentation-setup"
SCRIPT = SKILL / "scripts" / "transactional_proxy_bundle.py"
ASSETS = SKILL / "assets"
REFERENCE = SKILL / "references" / "proxy-bundle-transaction.md"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "galileo_proxy_bundle_transaction", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tx() -> ModuleType:
    return load_module()


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def protected_write(path: Path, payload: bytes, mode: int) -> None:
    path.write_bytes(payload)
    path.chmod(mode)


def proxy_config(filter_path: Path) -> bytes:
    return (
        "# Dedicated Galileo CONNECT proxy.\n"
        "User tinyproxy\n"
        "Group tinyproxy\n"
        "Port 18888\n"
        "Listen 127.0.0.1\n"
        "Timeout 30\n"
        "MaxClients 32\n"
        'PidFile "/run/tinyproxy-galileo/tinyproxy.pid"\n'
        "Syslog On\n"
        "LogLevel Info\n"
        "Allow 127.0.0.1\n"
        "ConnectPort 443\n"
        f'Filter "{filter_path}"\n'
        "FilterType ere\n"
        "FilterURLs No\n"
        "FilterCaseSensitive Yes\n"
        "FilterDefaultDeny Yes\n"
        "DisableViaHeader Yes\n"
    ).encode()


def provenance(tx: ModuleType, uid: int, gid: int) -> dict[str, Any]:
    return {
        "host_fingerprint": "1" * 64,
        "package": {"name": "tinyproxy", "version": "1.11.3-1"},
        "binary_package": {"name": "tinyproxy-bin", "version": "1.11.3-1"},
        "binary": {
            "path": str(tx.TINYPROXY_BINARY),
            "sha256": "2" * 64,
            "uid": 0,
            "gid": 0,
            "mode": 0o755,
            "size": 12345,
            "device": 1,
            "inode": 2,
            "mtime_ns": 3,
        },
        "identity": {
            "user": "tinyproxy",
            "group": "tinyproxy",
            "uid": max(uid, 1),
            "gid": max(gid, 1),
        },
    }


class FakeSystem:
    def __init__(
        self,
        static: dict[str, Any],
        unit_path: Path,
        units: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.static = copy.deepcopy(static)
        self.unit_path = unit_path
        self.units = copy.deepcopy(
            units
            or {
                "generic": {"enabled_state": "enabled", "active_state": "active"},
                "dedicated": {"enabled_state": "not-found", "active_state": "inactive"},
            }
        )
        self.initial_units = copy.deepcopy(self.units)
        self.actions: list[str] = []
        self.fail_once: str | None = None
        self.probe_calls = 0

    def _record(self, action: str) -> None:
        self.actions.append(action)
        if self.fail_once == action:
            self.fail_once = None
            raise RuntimeError("sensitive fake failure")

    def capture_static(self, request: dict[str, Any]) -> dict[str, Any]:
        requested = request["provenance"]
        observed = {
            "package_name": self.static["package"]["name"],
            "package_version": self.static["package"]["version"],
            "binary_package_name": self.static["binary_package"]["name"],
            "binary_package_version": self.static["binary_package"]["version"],
            "binary_path": self.static["binary"]["path"],
            "binary_sha256": self.static["binary"]["sha256"],
            "user": self.static["identity"]["user"],
            "group": self.static["identity"]["group"],
        }
        if any(requested[key] != value for key, value in observed.items()):
            raise RuntimeError("sensitive provenance mismatch")
        return copy.deepcopy(self.static)

    def verify_static(self, expected: dict[str, Any]) -> None:
        self._record("verify-static")
        if expected != self.static:
            raise RuntimeError("sensitive provenance drift")

    def capture_units(self) -> dict[str, dict[str, str]]:
        return copy.deepcopy(self.units)

    def query_unit(self, role: str) -> dict[str, str]:
        state = copy.deepcopy(self.units[role])
        if (
            role == "dedicated"
            and state["enabled_state"] == "not-found"
            and self.unit_path.exists()
        ):
            return {"enabled_state": "disabled", "active_state": "inactive"}
        return state

    def daemon_reload(self) -> None:
        self._record("daemon-reload")
        if (
            self.unit_path.exists()
            and self.units["dedicated"]["enabled_state"] == "not-found"
        ):
            self.units["dedicated"] = {
                "enabled_state": "disabled",
                "active_state": "inactive",
            }
        if not self.unit_path.exists():
            self.units["dedicated"] = {
                "enabled_state": "not-found",
                "active_state": "inactive",
            }

    def verify_unit(self, path: Path) -> None:
        self._record("verify-unit")
        assert path == self.unit_path
        assert path.exists()

    def _role(self, unit: str) -> str:
        return "generic" if unit == "tinyproxy.service" else "dedicated"

    def disable(self, unit: str) -> None:
        role = self._role(unit)
        self._record(f"disable-{role}")
        if self.units[role]["enabled_state"] == "not-found":
            raise RuntimeError("missing unit")
        self.units[role]["enabled_state"] = "disabled"

    def enable(self, unit: str) -> None:
        role = self._role(unit)
        self._record(f"enable-{role}")
        if self.units[role]["enabled_state"] == "not-found":
            raise RuntimeError("missing unit")
        self.units[role]["enabled_state"] = "enabled"

    def stop(self, unit: str) -> None:
        role = self._role(unit)
        self._record(f"stop-{role}")
        if self.units[role]["enabled_state"] == "not-found":
            raise RuntimeError("missing unit")
        self.units[role]["active_state"] = "inactive"

    def start(self, unit: str) -> None:
        role = self._role(unit)
        self._record(f"start-{role}")
        if self.units[role]["enabled_state"] == "not-found":
            raise RuntimeError("missing unit")
        self.units[role]["active_state"] = "active"

    def restart(self, unit: str) -> None:
        role = self._role(unit)
        self._record(f"restart-{role}")
        if self.units[role]["enabled_state"] == "not-found":
            raise RuntimeError("missing unit")
        self.units[role]["active_state"] = "active"

    def probes(self, _proxy: dict[str, Any]) -> dict[str, Any]:
        self._record("probes")
        self.probe_calls += 1
        return {
            "listener": {"checked": True, "ok": True},
            "denied_connect": {"checked": True, "ok": True, "status_code": 403},
            "allowed_connect": {"checked": True, "ok": True, "status_class": "2xx"},
        }


def make_case(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: bool = False,
    units: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    uid = os.geteuid()
    gid = os.getegid()
    root = tmp_path / "root"
    tinyproxy_dir = root / "etc/tinyproxy"
    systemd_dir = root / "etc/systemd/system"
    staging = root / "staging"
    state_parent = root / "var/lib"
    for directory in (tinyproxy_dir, systemd_dir, staging, state_parent):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in [root, *root.rglob("*")]:
        if directory.is_dir():
            directory.chmod(0o700)

    targets = {
        "proxy_filter": tinyproxy_dir / "galileo.filter",
        "proxy_config": tinyproxy_dir / "galileo.conf",
        "proxy_unit": systemd_dir / "galileo-tinyproxy.service",
    }
    monkeypatch.setattr(tx, "TARGETS", targets)

    payloads = {
        "proxy_filter": rb"^api\.demo-v2\.galileocloud\.io$" + b"\n",
        "proxy_config": proxy_config(targets["proxy_filter"]),
        "proxy_unit": (ASSETS / "galileo-tinyproxy.service").read_bytes(),
    }
    entries: list[dict[str, Any]] = []
    originals: dict[str, tuple[bytes, int]] = {}
    for role in tx.ROLES:
        if existing:
            original = (f"original-{role}\n".encode(), 0o640)
            protected_write(targets[role], *original)
            originals[role] = original
        source = staging / f"{role}.staged"
        protected_write(source, payloads[role], 0o644)
        entries.append(
            {
                "role": role,
                "source": str(source),
                "target": str(targets[role]),
                "sha256": sha(payloads[role]),
                "uid": uid,
                "gid": gid,
                "mode": "0644",
            }
        )
    request = {
        "schema_version": tx.REQUEST_SCHEMA,
        "state_root": str(state_parent / "galileo-proxy-transactions"),
        "provenance": {
            "package_name": "tinyproxy",
            "package_version": "1.11.3-1",
            "binary_package_name": "tinyproxy-bin",
            "binary_package_version": "1.11.3-1",
            "binary_path": str(tx.TINYPROXY_BINARY),
            "binary_sha256": "2" * 64,
            "user": "tinyproxy",
            "group": "tinyproxy",
        },
        "proxy": {
            "listen_host": "127.0.0.1",
            "listen_port": 18888,
            "allowed_connect_host": "api.demo-v2.galileocloud.io",
            "denied_connect_host": "example.invalid",
            "probe_timeout_seconds": 5,
        },
        "files": entries,
    }
    request_path = staging / "proxy-request.json"
    protected_write(
        request_path, (json.dumps(request, sort_keys=True) + "\n").encode(), 0o600
    )
    fake = FakeSystem(provenance(tx, uid, gid), targets["proxy_unit"], units)
    return {
        "uid": uid,
        "gid": gid,
        "request": request,
        "request_path": request_path,
        "targets": targets,
        "payloads": payloads,
        "originals": originals,
        "system": fake,
        "state_root": Path(request["state_root"]),
    }


def manifest_path(case: dict[str, Any], result: dict[str, Any]) -> Path:
    return case["state_root"] / f"generation-{result['generation']}" / "manifest.json"


def rewrite_request(case: dict[str, Any]) -> None:
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )


def test_apply_and_restore_absent_files_and_exact_unit_states(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_proxy_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert result["status"] == "applied"
    assert result["package_mutated"] is False
    assert result["probes"]["denied_connect"]["status_code"] == 403
    assert case["system"].units == {
        "generic": {"enabled_state": "disabled", "active_state": "inactive"},
        "dedicated": {"enabled_state": "enabled", "active_state": "active"},
    }
    for role, target in case["targets"].items():
        assert target.read_bytes() == case["payloads"][role]
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert "disable-generic" in case["system"].actions
    assert "stop-generic" in case["system"].actions
    assert "enable-dedicated" in case["system"].actions
    assert "restart-dedicated" in case["system"].actions

    restored = tx.restore_proxy_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert restored == {"status": "restored", "unit_state_restored": True}
    assert case["system"].units == case["system"].initial_units
    assert all(not target.exists() for target in case["targets"].values())
    assert not (case["state_root"] / "current.json").exists()


def test_existing_files_modes_and_xattrs_are_restored(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = {
        "generic": {"enabled_state": "disabled", "active_state": "inactive"},
        "dedicated": {"enabled_state": "enabled", "active_state": "active"},
    }
    case = make_case(tx, tmp_path, monkeypatch, existing=True, units=units)
    xattr_target = case["targets"]["proxy_config"]
    try:
        os.setxattr(
            xattr_target, "user.galileo-proxy-test", b"original", follow_symlinks=False
        )
    except (AttributeError, OSError):
        pytest.skip("test filesystem does not support user xattrs")
    result = tx.apply_proxy_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    tx.restore_proxy_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    for role, target in case["targets"].items():
        payload, mode = case["originals"][role]
        assert target.read_bytes() == payload
        assert stat.S_IMODE(target.stat().st_mode) == mode
    assert (
        os.getxattr(xattr_target, "user.galileo-proxy-test", follow_symlinks=False)
        == b"original"
    )
    assert case["system"].units == units


def test_provenance_mismatch_fails_before_state_or_file_mutation(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["request"]["provenance"]["package_version"] = "9.9.9"
    rewrite_request(case)
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert all(not target.exists() for target in case["targets"].values())
    assert not case["state_root"].exists()


@pytest.mark.parametrize(
    "attack", ["source_symlink", "source_hardlink", "target_symlink", "target_hardlink"]
)
def test_link_attacks_are_rejected_before_mutation(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    entry = next(
        item for item in case["request"]["files"] if item["role"] == "proxy_config"
    )
    attacked = Path(entry["source"] if attack.startswith("source") else entry["target"])
    decoy = case["request_path"].parent / "decoy"
    protected_write(decoy, b"decoy\n", 0o644)
    if attacked.exists() or attacked.is_symlink():
        attacked.unlink()
    if attack.endswith("symlink"):
        attacked.symlink_to(decoy)
    else:
        os.link(decoy, attacked)
    with pytest.raises(tx.TransactionError):
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert case["system"].actions == []


@pytest.mark.parametrize("role", ["proxy_filter", "proxy_config", "proxy_unit"])
def test_invalid_policy_source_is_rejected_before_mutation(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    entry = next(item for item in case["request"]["files"] if item["role"] == role)
    if role == "proxy_filter":
        payload = b".*\n"
    elif role == "proxy_config":
        payload = case["payloads"][role] + b"Upstream http attacker.invalid:8080\n"
    else:
        payload = case["payloads"][role].replace(b"User=tinyproxy", b"User=root")
    protected_write(Path(entry["source"]), payload, 0o644)
    entry["sha256"] = sha(payload)
    rewrite_request(case)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_source"
    assert all(not target.exists() for target in case["targets"].values())


def test_probe_failure_automatically_restores_files_and_both_units(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["system"].fail_once = "probes"
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.rollback == {
        "attempted": True,
        "ok": True,
        "recovery_required": False,
    }
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].units == case["system"].initial_units
    assert not (case["state_root"] / "current.json").exists()


def test_restart_side_effect_before_completion_checkpoint_is_recoverable(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    original_restart = case["system"].restart
    raised = False

    def restart_then_interrupt(unit: str) -> None:
        nonlocal raised
        original_restart(unit)
        if not raised:
            raised = True
            raise KeyboardInterrupt

    case["system"].restart = restart_then_interrupt
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "interrupted"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].units == case["system"].initial_units


def test_interrupt_after_durable_intent_automatically_rolls_back(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    raised = False

    def interrupt(phase: str, intent: dict[str, Any] | None) -> None:
        nonlocal raised
        if (
            not raised
            and phase == "applying"
            and intent == {"kind": "apply_action", "index": 5}
        ):
            raised = True
            raise KeyboardInterrupt

    monkeypatch.setattr(tx, "after_checkpoint", interrupt)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "interrupted"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].units == case["system"].initial_units


def test_explicit_restore_recovers_after_restore_action_failure(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_proxy_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    case["system"].fail_once = "daemon-reload"
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.restore_proxy_bundle(
            manifest_path(case, result),
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.rollback["recovery_required"] is True
    recovered = tx.restore_proxy_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert recovered["status"] == "restored"
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].units == case["system"].initial_units


def test_source_race_is_detected_and_automatic_restore_completes(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    entry = next(
        item for item in case["request"]["files"] if item["role"] == "proxy_config"
    )
    changed = False

    def race(role: str) -> None:
        nonlocal changed
        if role == "proxy_config" and not changed:
            changed = True
            protected_write(Path(entry["source"]), b"changed\n", 0o644)

    monkeypatch.setattr(tx, "before_source_recheck", race)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "source_changed"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())


def test_unit_state_drift_at_file_boundary_fails_closed_and_restores(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    changed = False

    def drift(role: str, operation: str) -> None:
        nonlocal changed
        if role == "proxy_filter" and operation == "install" and not changed:
            changed = True
            case["system"].units["generic"]["active_state"] = "inactive"

    monkeypatch.setattr(tx, "before_target_commit", drift)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "unit_state_drift"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].units == case["system"].initial_units


def test_stale_not_found_state_with_existing_dedicated_unit_is_rejected(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch, existing=True)
    originals = {role: target.read_bytes() for role, target in case["targets"].items()}
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "unit_state_failed"
    assert {
        role: target.read_bytes() for role, target in case["targets"].items()
    } == originals


def test_manifest_hash_is_bound_to_current_generation(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_proxy_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    path = manifest_path(case, result)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["request_sha256"] = "9" * 64
    protected_write(path, (json.dumps(document, sort_keys=True) + "\n").encode(), 0o600)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.restore_proxy_bundle(
            path,
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "stale_transaction"


def test_current_generation_blocks_overlap(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_proxy_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "current_generation"
    tx.restore_proxy_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )


def test_exact_target_allowlist_is_enforced(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["request"]["files"][0]["target"] = str(
        case["targets"]["proxy_filter"].with_name("other.filter")
    )
    rewrite_request(case)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_proxy_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_path"


def test_cli_failure_is_sanitized_and_does_not_echo_path(
    tx: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_path = "/private/do-not-print-proxy-request"
    monkeypatch.setattr(
        tx,
        "validate_runtime",
        lambda: (_ for _ in ()).throw(
            tx.TransactionError("root_required", "root required")
        ),
    )
    assert tx.main(["apply", "--request", secret_path]) == 1
    captured = capsys.readouterr()
    document = json.loads(captured.err)
    assert document["error"]["code"] == "root_required"
    assert secret_path not in captured.err
    assert captured.out == ""


def test_listener_inventory_requires_one_exact_ipv4_loopback_socket(
    tx: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    system = object.__new__(tx.ProxySystem)
    system.ss = "/usr/bin/ss"

    def inventory(stdout: str):
        return subprocess.CompletedProcess(["ss"], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        tx,
        "run_command",
        lambda *_args, **_kwargs: inventory("LISTEN 0 32 127.0.0.1:18888 0.0.0.0:*\n"),
    )
    assert system.listener("127.0.0.1", 18888) == {"checked": True, "ok": True}

    monkeypatch.setattr(
        tx,
        "run_command",
        lambda *_args, **_kwargs: inventory(
            "LISTEN 0 32 127.0.0.1:18888 0.0.0.0:*\n"
            "LISTEN 0 32 0.0.0.0:18888 0.0.0.0:*\n"
        ),
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        system.listener("127.0.0.1", 18888)
    assert exc_info.value.code == "listener_check_failed"


def test_connect_probe_sends_no_credential_and_parses_only_status_line(
    tx: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[bytes] = []

    class Peer:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def settimeout(self, _timeout: float) -> None:
            return None

        def sendall(self, payload: bytes) -> None:
            requests.append(payload)

        def recv(self, _size: int) -> bytes:
            return b"HTTP/1.1 403 Filtered\r\n\r\n"

    monkeypatch.setattr(
        tx.socket, "create_connection", lambda *_args, **_kwargs: Peer()
    )
    status = tx.ProxySystem._connect_status("127.0.0.1", 18888, "example.invalid", 2)
    assert status == 403
    assert requests == [
        b"CONNECT example.invalid:443 HTTP/1.1\r\n"
        b"Host: example.invalid:443\r\n"
        b"Proxy-Connection: close\r\n\r\n"
    ]
    assert b"Authorization" not in requests[0]
    assert b"API-Key" not in requests[0]


def test_script_is_executable_and_reference_states_composition_order() -> None:
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    text = REFERENCE.read_text(encoding="utf-8")
    assert "Collector YAML" in text
    assert "Collector runtime bundle" in text
    assert "proxy bundle" in text
    assert "YAML first" in text

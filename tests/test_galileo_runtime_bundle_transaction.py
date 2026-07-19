from __future__ import annotations

import copy
import hashlib
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
    / "transactional_runtime_bundle.py"
)


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "galileo_transactional_runtime_bundle", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tx() -> ModuleType:
    return load_module()


class FakeSystem:
    def __init__(self, provenance: dict[str, Any]) -> None:
        self.provenance = copy.deepcopy(provenance)
        self.actions: list[str] = []
        self.verify_calls = 0
        self.runtime_contract_checks = 0
        self.fail_restart_count = 0

    def capture(
        self, _request: dict[str, Any], *, managed_dropin: Path
    ) -> dict[str, Any]:
        del managed_dropin
        return copy.deepcopy(self.provenance)

    def verify(self, expected: dict[str, Any], *, managed_dropin: Path) -> None:
        del managed_dropin
        self.verify_calls += 1
        if expected != self.provenance:
            raise RuntimeError("unexpected provenance")

    def daemon_reload(self, _service: str) -> None:
        self.actions.append("daemon-reload")

    def restart(self, _service: str) -> None:
        self.actions.append("restart")
        if self.fail_restart_count:
            self.fail_restart_count -= 1
            raise RuntimeError("sensitive restart output")

    def health(self, _url: str, _timeout: float) -> dict[str, Any]:
        self.actions.append("health")
        return {"checked": True, "ok": True, "status_code": 200}

    def verify_runtime_contract(
        self, *, service: str, managed_dropin: Path, wrapper: Path
    ) -> None:
        del service, managed_dropin, wrapper
        self.runtime_contract_checks += 1


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def protected_write(path: Path, payload: bytes, mode: int) -> None:
    path.write_bytes(payload)
    path.chmod(mode)


def provenance(tmp_path: Path, uid: int, gid: int, service: str) -> dict[str, Any]:
    def file_record(path: Path, digest: str, mode: int) -> dict[str, Any]:
        return {
            "path": str(path),
            "sha256": digest,
            "uid": uid,
            "gid": gid,
            "mode": mode,
            "size": 8,
            "device": 1,
            "inode": 2,
            "mtime_ns": 3,
        }

    return {
        "host_fingerprint": "1" * 64,
        "package": {"name": "splunk-otel-collector", "version": "0.156.0"},
        "collector_binary": file_record(tmp_path / "usr/bin/otelcol", "2" * 64, 0o755),
        "collector_config": {
            "path": str(
                tmp_path / "etc/splunk-otel-collector/lemonade-agent-config.yaml"
            ),
            "sha256": sha(b"receivers: {}\n"),
            "uid": 0,
            "gid": 0,
            "mode": 0o644,
            "size": len(b"receivers: {}\n"),
        },
        "unit": {
            "name": service,
            "unit_file_state": "enabled",
            "user": "splunk-otel-collector",
            "group": "splunk-otel-collector",
            "service_uid": uid,
            "service_gid": gid,
            "fragment": file_record(
                tmp_path / "usr/lib/systemd/system/collector.service",
                "3" * 64,
                0o644,
            ),
            "unmanaged_dropins": [],
        },
    }


def make_case(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    actions: dict[str, str] | None = None,
    existing: bool = False,
) -> dict[str, Any]:
    uid = os.geteuid()
    gid = os.getegid()
    service = "splunk-otel-collector.service"
    root = tmp_path / "root"
    config = root / "etc/splunk-otel-collector"
    secrets_dir = config / "secrets"
    libexec = root / "usr/local/libexec"
    systemd = root / "etc/systemd/system"
    dropin_dir = systemd / f"{service}.d"
    staging = root / "staging"
    state_parent = root / "var/lib"
    for directory in (config, secrets_dir, libexec, dropin_dir, staging, state_parent):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in [root, *root.rglob("*")]:
        if directory.is_dir():
            directory.chmod(0o700)
    secrets_dir.chmod(0o750)

    monkeypatch.setattr(tx, "RUNTIME_CONFIG_DIR", config)
    monkeypatch.setattr(tx, "LIBEXEC_DIR", libexec)
    monkeypatch.setattr(tx, "SYSTEMD_DIR", systemd)
    monkeypatch.setattr(tx, "COLLECTOR_BINARY_PATH", root / "usr/bin/otelcol")
    monkeypatch.setattr(
        tx,
        "COLLECTOR_CONFIG_PATH",
        config / "lemonade-agent-config.yaml",
    )
    queue_base = root / "var/lib/splunk-otel-collector/galileo-queue"
    monkeypatch.setattr(tx, "GALILEO_QUEUE_BASE_DIR", queue_base)
    queue_base.mkdir(parents=True)
    queue_base.chmod(0o700)
    collector_config_payload = b"receivers: {}\n"
    protected_write(tx.COLLECTOR_CONFIG_PATH, collector_config_payload, 0o644)

    endpoint = "https://api.example.invalid/otel/v1/traces"
    project_id = "project-id"
    log_stream_id = "log-stream-id"
    fingerprint = sha(
        json.dumps(
            {
                "endpoint": endpoint,
                "log_stream": log_stream_id,
                "project": project_id,
                "selector_kind": "ids",
                "version": 1,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )

    role_data = {
        "routing_env": (
            (
                f"GALILEO_OTLP_TRACES_ENDPOINT={endpoint}\n"
                "GALILEO_EXPECTED_ORIGIN=https://api.example.invalid\n"
                f"GALILEO_API_KEY_FILE={secrets_dir / 'galileo_api_key'}\n"
                f"GALILEO_PROXY_URL={tx.GALILEO_PROXY_URL}\n"
                f"GALILEO_TINYPROXY_EVIDENCE_FILE={config / 'galileo-evidence.json'}\n"
                f"GALILEO_DESTINATION_FINGERPRINT={fingerprint}\n"
                f"GALILEO_QUEUE_STORAGE_DIRECTORY={queue_base / fingerprint}\n"
                f"GALILEO_PROJECT_ID={project_id}\n"
                f"GALILEO_LOG_STREAM_ID={log_stream_id}\n"
            ).encode(),
            0o600,
        ),
        "protected_evidence": (b'{"schema":"protected-evidence"}\n', 0o440),
        "runtime_wrapper": (b"#!/usr/bin/env python3\nprint('wrapper')\n", 0o755),
        "galileo_key": (b"synthetic-test-key\n", 0o600),
        "collector_dropin": (b"placeholder", 0o644),
    }
    targets = {
        "routing_env": config / "galileo-routing.env",
        "protected_evidence": config / "galileo-evidence.json",
        "runtime_wrapper": libexec / "collector_runtime_wrapper.py",
        "galileo_key": secrets_dir / "galileo_api_key",
        "collector_dropin": dropin_dir / "90-galileo-runtime.conf",
    }
    role_data["collector_dropin"] = (
        (
            "[Unit]\n"
            f"Wants={tx.GALILEO_PROXY_SERVICE}\n"
            f"After={tx.GALILEO_PROXY_SERVICE}\n"
            "\n"
            "[Service]\n"
            f"EnvironmentFile={targets['routing_env']}\n"
            "ExecStart=\n"
            f"ExecStart={tx.PYTHON_BINARY_PATH} {targets['runtime_wrapper']} -- "
            f"{tx.COLLECTOR_BINARY_PATH} "
            f"--config={tx.COLLECTOR_CONFIG_PATH}\n"
        ).encode(),
        0o644,
    )
    entries: list[dict[str, Any]] = []
    selected_actions = actions or {role: "install" for role in tx.ROLES}
    originals: dict[str, tuple[bytes, int]] = {}
    for role in tx.ROLES:
        action = selected_actions[role]
        if existing:
            original = (
                f"original-{role}\n".encode(),
                0o640 if role != "runtime_wrapper" else 0o750,
            )
            protected_write(targets[role], original[0], original[1])
            originals[role] = original
        if action == "remove":
            entries.append(
                {"role": role, "action": "remove", "target": str(targets[role])}
            )
            continue
        payload, mode = role_data[role]
        source = staging / f"{role}.staged"
        protected_write(source, payload, mode)
        entries.append(
            {
                "role": role,
                "action": "install",
                "source": str(source),
                "target": str(targets[role]),
                "sha256": sha(payload),
                "uid": uid,
                "gid": gid,
                "mode": f"0{mode:o}",
            }
        )
    request = {
        "schema_version": tx.REQUEST_SCHEMA,
        "state_root": str(state_parent / "galileo-runtime-transactions"),
        "service": {
            "name": service,
            "health_url": "http://127.0.0.1:13133/",
            "health_timeout_seconds": 5,
        },
        "provenance": {
            "package_name": "splunk-otel-collector",
            "package_version": "0.156.0",
            "collector_binary": str(tx.COLLECTOR_BINARY_PATH),
            "collector_binary_sha256": "2" * 64,
            "collector_config_sha256": sha(collector_config_payload),
            "unit_fragment_sha256": "3" * 64,
        },
        "files": entries,
    }
    request_path = staging / "request.json"
    protected_write(
        request_path,
        (json.dumps(request, sort_keys=True) + "\n").encode(),
        0o600,
    )
    fake = FakeSystem(provenance(root, uid, gid, service))
    return {
        "uid": uid,
        "gid": gid,
        "request": request,
        "request_path": request_path,
        "targets": targets,
        "role_data": role_data,
        "originals": originals,
        "system": fake,
        "state_root": Path(request["state_root"]),
    }


def manifest_path(case: dict[str, Any], result: dict[str, Any]) -> Path:
    return case["state_root"] / f"generation-{result['generation']}" / "manifest.json"


def replace_staged_payload(
    case: dict[str, Any], role: str, payload: bytes, mode: int
) -> None:
    entry = next(item for item in case["request"]["files"] if item["role"] == role)
    protected_write(Path(entry["source"]), payload, mode)
    entry["sha256"] = sha(payload)
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )


def test_apply_orders_dropin_last_and_restore_deletes_originally_absent_files(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    commits: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tx,
        "before_target_commit",
        lambda role, operation: commits.append((role, operation)),
    )
    result = tx.apply_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert result["status"] == "applied"
    assert [role for role, operation in commits if operation == "install"] == list(
        tx.APPLY_ORDER
    )
    assert commits[4] == ("collector_dropin", "install")
    assert case["system"].actions == ["daemon-reload", "restart", "health"]
    assert case["system"].runtime_contract_checks == 4
    for role, target in case["targets"].items():
        payload, mode = case["role_data"][role]
        assert target.read_bytes() == payload
        assert stat.S_IMODE(target.stat().st_mode) == mode

    restored = tx.restore_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert restored["status"] == "restored"
    assert not (case["state_root"] / "current.json").exists()
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].actions == [
        "daemon-reload",
        "restart",
        "health",
        "daemon-reload",
        "restart",
        "health",
    ]


def test_existing_install_and_remove_targets_restore_exact_content_and_mode(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actions = {
        "routing_env": "remove",
        "protected_evidence": "remove",
        "runtime_wrapper": "install",
        "galileo_key": "remove",
        "collector_dropin": "remove",
    }
    case = make_case(tx, tmp_path, monkeypatch, actions=actions, existing=True)
    result = tx.apply_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert not case["targets"]["protected_evidence"].exists()
    assert not case["targets"]["galileo_key"].exists()
    tx.restore_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    for role, target in case["targets"].items():
        payload, mode = case["originals"][role]
        assert target.read_bytes() == payload
        assert stat.S_IMODE(target.stat().st_mode) == mode


def test_protected_evidence_must_be_collector_group_readable_0440(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    evidence = next(
        item
        for item in case["request"]["files"]
        if item["role"] == "protected_evidence"
    )
    evidence["mode"] = "0400"
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "evidence_unreadable"
    assert all(not target.exists() for target in case["targets"].values())


def test_staged_mode_must_exactly_match_the_declared_role_contract(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    routing = next(
        item for item in case["request"]["files"] if item["role"] == "routing_env"
    )
    Path(routing["source"]).chmod(0o640)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "source_mismatch"
    assert all(not target.exists() for target in case["targets"].values())


def test_nested_key_parent_is_exact_root_collector_group_0750(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["targets"]["galileo_key"].parent.chmod(0o700)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "unsafe_secret_directory"


def test_key_target_has_one_exact_allowlisted_path(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    key = next(
        item for item in case["request"]["files"] if item["role"] == "galileo_key"
    )
    key["target"] = str(tx.RUNTIME_CONFIG_DIR / "galileo-api.key")
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )
    with pytest.raises(tx.TransactionError, match="key target"):
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "LD_PRELOAD=/tmp/injected.so\n",
        "PYTHONPATH=/tmp/injected\n",
        "PATH=/tmp/injected\n",
        "GALILEO_API_KEY=must-not-enter-service-env\n",
        "#comment\n",
    ),
)
def test_routing_environment_rejects_unknown_loader_inline_key_and_comment(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    original = case["role_data"]["routing_env"][0]
    replace_staged_payload(case, "routing_env", original + mutation.encode(), 0o600)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_routing_env"
    assert case["system"].actions == []
    assert all(not target.exists() for target in case["targets"].values())


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate",
        "quote",
        "backslash",
        "whitespace",
        "wrong_queue_parent",
        "wrong_key_path",
        "wrong_evidence_path",
        "wrong_origin",
        "wrong_fingerprint",
    ),
)
def test_routing_environment_rejects_noncanonical_or_unbound_values(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    text = case["role_data"]["routing_env"][0].decode("ascii")
    fingerprint = next(
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith("GALILEO_DESTINATION_FINGERPRINT=")
    )
    if mutation == "duplicate":
        text += "GALILEO_PROJECT_ID=project-id\n"
    elif mutation == "quote":
        text = text.replace(
            f"GALILEO_PROXY_URL={tx.GALILEO_PROXY_URL}",
            f'GALILEO_PROXY_URL="{tx.GALILEO_PROXY_URL}"',
        )
    elif mutation == "backslash":
        text = text.replace(
            "GALILEO_PROJECT_ID=project-id", r"GALILEO_PROJECT_ID=project\id"
        )
    elif mutation == "whitespace":
        text = text.replace(
            "GALILEO_PROJECT_ID=project-id", "GALILEO_PROJECT_ID=project id"
        )
    elif mutation == "wrong_queue_parent":
        text = text.replace(
            f"GALILEO_QUEUE_STORAGE_DIRECTORY={tx.GALILEO_QUEUE_BASE_DIR / fingerprint}",
            f"GALILEO_QUEUE_STORAGE_DIRECTORY=/var/tmp/{fingerprint}",
        )
    elif mutation == "wrong_key_path":
        text = text.replace(
            f"GALILEO_API_KEY_FILE={case['targets']['galileo_key']}",
            "GALILEO_API_KEY_FILE=/etc/alternate.key",
        )
    elif mutation == "wrong_evidence_path":
        text = text.replace(
            f"GALILEO_TINYPROXY_EVIDENCE_FILE={case['targets']['protected_evidence']}",
            "GALILEO_TINYPROXY_EVIDENCE_FILE=/etc/alternate.json",
        )
    elif mutation == "wrong_origin":
        text = text.replace(
            "GALILEO_EXPECTED_ORIGIN=https://api.example.invalid",
            "GALILEO_EXPECTED_ORIGIN=https://other.example.invalid",
        )
    else:
        text = text.replace(fingerprint, "0" * 64, 1)
    replace_staged_payload(case, "routing_env", text.encode("ascii"), 0o600)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_routing_env"
    assert case["system"].actions == []


@pytest.mark.parametrize(
    "mutation",
    [
        "alternate_environment",
        "duplicate_environment",
        "alternate_wrapper",
        "alternate_binary",
        "alternate_config",
        "extra_argv",
        "extra_service_directive",
        "alternate_proxy_dependency",
        "duplicate_unit_section",
        "duplicate_execstart",
    ],
)
def test_dropin_rejects_every_alternate_directive_path_or_argv(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    dropin = next(
        item for item in case["request"]["files"] if item["role"] == "collector_dropin"
    )
    source = Path(dropin["source"])
    text = source.read_text(encoding="utf-8")
    if mutation == "alternate_environment":
        text = text.replace(
            f"EnvironmentFile={case['targets']['routing_env']}",
            "EnvironmentFile=/etc/alternate.env",
        )
    elif mutation == "duplicate_environment":
        text = text.replace(
            "ExecStart=\n",
            f"EnvironmentFile={case['targets']['routing_env']}\nExecStart=\n",
        )
    elif mutation == "alternate_wrapper":
        text = text.replace(
            str(case["targets"]["runtime_wrapper"]), "/usr/local/bin/alternate"
        )
    elif mutation == "alternate_binary":
        text = text.replace(str(tx.COLLECTOR_BINARY_PATH), "/usr/bin/otelcol-contrib")
    elif mutation == "alternate_config":
        text = text.replace(str(tx.COLLECTOR_CONFIG_PATH), "/etc/otel/alternate.yaml")
    elif mutation == "extra_argv":
        text = text.replace("\n", " --feature-gate=unsafe\n", 4)
    elif mutation == "extra_service_directive":
        text += "User=root\n"
    elif mutation == "alternate_proxy_dependency":
        text = text.replace(
            tx.GALILEO_PROXY_SERVICE,
            "alternate-proxy.service",
            1,
        )
    elif mutation == "duplicate_unit_section":
        text += "[Unit]\nAfter=network-online.target\n"
    else:
        text += (
            f"ExecStart={case['targets']['runtime_wrapper']} -- "
            f"{tx.COLLECTOR_BINARY_PATH} --config={tx.COLLECTOR_CONFIG_PATH}\n"
        )
    payload = text.encode()
    protected_write(source, payload, 0o644)
    dropin["sha256"] = sha(payload)
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_dropin"
    assert case["system"].actions == []
    assert all(not target.exists() for target in case["targets"].values())


def effective_properties(tx: ModuleType, case: dict[str, Any]) -> dict[str, str]:
    wrapper = case["targets"]["runtime_wrapper"]
    argv = (
        f"{tx.PYTHON_BINARY_PATH} {wrapper} -- {tx.COLLECTOR_BINARY_PATH} "
        f"--config={tx.COLLECTOR_CONFIG_PATH}"
    )
    return {
        "Id": tx.COLLECTOR_SERVICE,
        "LoadState": "loaded",
        "ActiveState": "active",
        "UnitFileState": "enabled",
        "FragmentPath": str(
            Path(case["request"]["state_root"]).parent / "collector.service"
        ),
        "DropInPaths": str(case["targets"]["collector_dropin"]),
        "User": "splunk-otel-collector",
        "Group": "splunk-otel-collector",
        "ExecStart": (
            f"{{ path={tx.PYTHON_BINARY_PATH} ; argv[]={argv} ; "
            "ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; "
            "pid=0 ; code=(null) ; status=0/0 }"
        ),
        "Wants": f"network-online.target {tx.GALILEO_PROXY_SERVICE}",
        "After": f"network.target {tx.GALILEO_PROXY_SERVICE}",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_dropin",
        "shadow_dropin",
        "alternate_exec",
        "extra_argv",
        "missing_wants",
        "missing_after",
    ),
)
def test_effective_runtime_contract_rejects_shadow_or_merged_semantic_drift(
    tx: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    properties = effective_properties(tx, case)
    if mutation == "missing_dropin":
        properties["DropInPaths"] = ""
    elif mutation == "shadow_dropin":
        properties["DropInPaths"] = str(
            Path("/run/systemd/system")
            / f"{tx.COLLECTOR_SERVICE}.d/90-galileo-runtime.conf"
        )
    elif mutation == "alternate_exec":
        properties["ExecStart"] = properties["ExecStart"].replace(
            str(tx.PYTHON_BINARY_PATH), str(tx.COLLECTOR_BINARY_PATH), 1
        )
    elif mutation == "extra_argv":
        properties["ExecStart"] = properties["ExecStart"].replace(
            " ; ignore_errors=no", " --unsafe ; ignore_errors=no"
        )
    elif mutation == "missing_wants":
        properties["Wants"] = "network-online.target"
    else:
        properties["After"] = "network.target"
    monkeypatch.setattr(tx, "systemd_properties", lambda *_args: properties)
    runtime = object.__new__(tx.RuntimeSystem)
    runtime.systemctl = "/usr/bin/systemctl"
    runtime.owner_uid = 0
    with pytest.raises(tx.TransactionError) as exc_info:
        runtime.verify_runtime_contract(
            service=tx.COLLECTOR_SERVICE,
            managed_dropin=case["targets"]["collector_dropin"],
            wrapper=case["targets"]["runtime_wrapper"],
        )
    assert exc_info.value.code == "effective_unit_mismatch"


def test_effective_runtime_contract_accepts_only_exact_loaded_semantics(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    properties = effective_properties(tx, case)
    monkeypatch.setattr(tx, "systemd_properties", lambda *_args: properties)
    runtime = object.__new__(tx.RuntimeSystem)
    runtime.systemctl = "/usr/bin/systemctl"
    runtime.owner_uid = 0
    runtime.verify_runtime_contract(
        service=tx.COLLECTOR_SERVICE,
        managed_dropin=case["targets"]["collector_dropin"],
        wrapper=case["targets"]["runtime_wrapper"],
    )


def test_unmanaged_dropin_is_rejected_before_runtime_mutation(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    properties = effective_properties(tx, case)
    properties["User"] = ""
    properties["Group"] = ""
    properties["DropInPaths"] = "/etc/systemd/system/collector.service.d/99-other.conf"
    monkeypatch.setattr(tx, "systemd_properties", lambda *_args: properties)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.stable_unit_provenance(
            "/usr/bin/systemctl",
            tx.COLLECTOR_SERVICE,
            case["targets"]["collector_dropin"],
            owner_uid=0,
        )
    assert exc_info.value.code == "unmanaged_dropin"


def test_runtime_capture_rejects_reviewed_collector_config_hash_drift(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    snapshot = copy.deepcopy(case["system"].provenance)
    snapshot["collector_config"]["sha256"] = "f" * 64
    runtime = object.__new__(tx.RuntimeSystem)
    runtime.owner_uid = 0
    monkeypatch.setattr(runtime, "_snapshot", lambda **_kwargs: (snapshot, "active"))
    with pytest.raises(tx.TransactionError) as exc_info:
        runtime.capture(
            tx.parse_request(case["request"]),
            managed_dropin=case["targets"]["collector_dropin"],
        )
    assert exc_info.value.code == "collector_config_drift"


def test_service_name_is_exactly_allowlisted(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["request"]["service"]["name"] = "ssh.service"
    dropin = next(
        item for item in case["request"]["files"] if item["role"] == "collector_dropin"
    )
    dropin["target"] = str(tx.SYSTEMD_DIR / "ssh.service.d/90-galileo-runtime.conf")
    protected_write(
        case["request_path"],
        (json.dumps(case["request"], sort_keys=True) + "\n").encode(),
        0o600,
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "invalid_service"


def test_existing_extended_attributes_are_restored_when_supported(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch, existing=True)
    target = case["targets"]["routing_env"]
    name = "user.galileo-runtime-test"
    try:
        os.setxattr(target, name, b"original", follow_symlinks=False)
    except (AttributeError, OSError):
        pytest.skip("test filesystem does not support user extended attributes")
    result = tx.apply_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    tx.restore_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert os.getxattr(target, name, follow_symlinks=False) == b"original"


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
    routing = next(
        item for item in case["request"]["files"] if item["role"] == "routing_env"
    )
    decoy = case["request_path"].parent / "decoy"
    protected_write(decoy, b"decoy\n", 0o600)
    if attack.startswith("source"):
        path = Path(routing["source"])
    else:
        path = Path(routing["target"])
    if path.exists() or path.is_symlink():
        path.unlink()
    if attack.endswith("symlink"):
        path.symlink_to(decoy)
    else:
        os.link(decoy, path)
    with pytest.raises(tx.TransactionError):
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert case["system"].actions == []


def test_writable_target_ancestor_is_rejected(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    tx.RUNTIME_CONFIG_DIR.chmod(0o770)
    with pytest.raises(tx.TransactionError, match="ancestors"):
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )


def test_durable_interruption_automatically_rolls_back_partial_files(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    raised = False

    def interrupt(phase: str, intent: dict[str, Any] | None) -> None:
        nonlocal raised
        if (
            not raised
            and phase == "applying"
            and intent == {"kind": "apply_file", "index": 2}
        ):
            raised = True
            raise KeyboardInterrupt

    monkeypatch.setattr(tx, "after_checkpoint", interrupt)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "interrupted"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())
    assert not (case["state_root"] / "current.json").exists()


def test_restart_failure_automatically_restores_bundle(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    case["system"].fail_restart_count = 1
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())
    assert case["system"].actions.count("restart") == 2


def test_explicit_restore_resumes_after_side_effect_before_checkpoint(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    original_verify = tx.verify_boundary
    raised = False

    def fail_after_side_effect(*args: Any, **kwargs: Any) -> None:
        nonlocal raised
        original_verify(*args, **kwargs)
        if not raised and kwargs.get("boundary") == "after-restore-file-1":
            raised = True
            raise tx.TransactionError("interrupted", "transaction interrupted")

    monkeypatch.setattr(tx, "verify_boundary", fail_after_side_effect)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.restore_bundle(
            manifest_path(case, result),
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.rollback["recovery_required"] is True
    monkeypatch.setattr(tx, "verify_boundary", original_verify)
    restored = tx.restore_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    assert restored["status"] == "restored"
    assert all(not target.exists() for target in case["targets"].values())


def test_current_generation_blocks_overlapping_apply(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    result = tx.apply_bundle(
        case["request_path"],
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "current_generation"
    tx.restore_bundle(
        manifest_path(case, result),
        system=case["system"],
        owner_uid=case["uid"],
        owner_gid=case["gid"],
    )


def test_source_race_is_detected_and_partial_apply_rolls_back(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    wrapper = next(
        item for item in case["request"]["files"] if item["role"] == "runtime_wrapper"
    )
    changed = False

    def race(role: str) -> None:
        nonlocal changed
        if role == "runtime_wrapper" and not changed:
            changed = True
            protected_write(Path(wrapper["source"]), b"changed\n", 0o755)

    monkeypatch.setattr(tx, "before_source_recheck", race)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "source_changed"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())


def test_provenance_race_at_action_boundary_rolls_back(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    raised = False

    def race(boundary: str) -> None:
        nonlocal raised
        if boundary == "before-apply-file-2" and not raised:
            raised = True
            raise tx.TransactionError("provenance_drift", "runtime provenance changed")

    monkeypatch.setattr(tx, "before_provenance_check", race)
    with pytest.raises(tx.TransactionError) as exc_info:
        tx.apply_bundle(
            case["request_path"],
            system=case["system"],
            owner_uid=case["uid"],
            owner_gid=case["gid"],
        )
    assert exc_info.value.code == "provenance_drift"
    assert exc_info.value.rollback["ok"] is True
    assert all(not target.exists() for target in case["targets"].values())


def test_lock_is_nonoverlapping(
    tx: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make_case(tx, tmp_path, monkeypatch)
    tx.ensure_state_root(case["state_root"], owner_uid=case["uid"])
    with tx.acquire_lock(
        case["state_root"], owner_uid=case["uid"], owner_gid=case["gid"]
    ):
        with pytest.raises(tx.TransactionError) as exc_info:
            tx.acquire_lock(
                case["state_root"], owner_uid=case["uid"], owner_gid=case["gid"]
            )
    assert exc_info.value.code == "transaction_busy"


def test_cli_failure_is_sanitized_json_without_rejected_path(
    tx: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_path = "/private/do-not-print-secret-value"
    monkeypatch.setattr(
        tx,
        "validate_runtime",
        lambda: (_ for _ in ()).throw(
            tx.TransactionError("root_required", "apply and restore require root")
        ),
    )
    assert tx.main(["apply", "--request", secret_path]) == 1
    captured = capsys.readouterr()
    document = json.loads(captured.err)
    assert document["error"]["code"] == "root_required"
    assert secret_path not in captured.err
    assert captured.out == ""


def test_script_is_executable() -> None:
    assert SCRIPT.stat().st_mode & stat.S_IXUSR

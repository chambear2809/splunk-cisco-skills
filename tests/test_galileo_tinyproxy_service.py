from __future__ import annotations

import configparser
import importlib.util
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "galileo-lemonade-instrumentation-setup"
ASSETS = SKILL / "assets"
WRAPPER = SKILL / "scripts" / "collector_runtime_wrapper.py"


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "galileo_tinyproxy_service_wrapper", WRAPPER
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    with (ASSETS / "galileo-tinyproxy.service").open(encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def read_proxy_config() -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for raw_line in (
        (ASSETS / "galileo-tinyproxy.conf").read_text(encoding="utf-8").splitlines()
    ):
        words = shlex.split(raw_line, comments=True, posix=True)
        if words:
            assert words[0] not in directives
            directives[words[0]] = words[1:]
    return directives


def test_dedicated_tinyproxy_unit_is_one_exact_sandboxed_policy() -> None:
    unit = read_unit()
    assert unit.sections() == ["Unit", "Service", "Install"]
    assert dict(unit["Unit"]) == {
        "Description": "Dedicated exact-host egress proxy for Galileo OTLP",
        "Documentation": "https://tinyproxy.github.io/",
        "Wants": "network-online.target",
        "After": "network-online.target",
        "Before": "splunk-otel-collector.service",
    }
    assert dict(unit["Service"]) == {
        "Type": "simple",
        "ExecStart": "/usr/bin/tinyproxy -d -c /etc/tinyproxy/galileo.conf",
        "Restart": "on-failure",
        "RestartSec": "2s",
        "TimeoutStartSec": "15s",
        "TimeoutStopSec": "15s",
        "User": "tinyproxy",
        "Group": "tinyproxy",
        "RuntimeDirectory": "tinyproxy-galileo",
        "RuntimeDirectoryMode": "0755",
        "UMask": "0077",
        "NoNewPrivileges": "yes",
        "PrivateDevices": "yes",
        "PrivateTmp": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "ProtectKernelLogs": "yes",
        "ProtectControlGroups": "yes",
        "ProtectClock": "yes",
        "ProtectHostname": "yes",
        "LockPersonality": "yes",
        "MemoryDenyWriteExecute": "yes",
        "RestrictNamespaces": "yes",
        "RestrictSUIDSGID": "yes",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
        "SystemCallArchitectures": "native",
        "TasksMax": "64",
        "LimitNOFILE": "1024",
        "StandardOutput": "journal",
        "StandardError": "journal",
    }
    assert dict(unit["Install"]) == {"WantedBy": "multi-user.target"}


def test_tinyproxy_config_and_systemd_runtime_contract_are_aligned() -> None:
    service = read_unit()["Service"]
    config = read_proxy_config()

    assert config["User"] == [service["User"]]
    assert config["Group"] == [service["Group"]]
    assert config["PidFile"] == [f"/run/{service['RuntimeDirectory']}/tinyproxy.pid"]
    assert int(config["Port"][0]) > 1024
    assert int(service["TasksMax"]) >= int(config["MaxClients"][0]) + 2
    assert config["Listen"] == ["127.0.0.1"]
    assert config["Allow"] == ["127.0.0.1"]
    assert config["ConnectPort"] == ["443"]
    assert config["Syslog"] == ["On"]
    assert "AF_UNIX" in service["RestrictAddressFamilies"].split()
    assert config["FilterDefaultDeny"] == ["Yes"]

    # Keep the packaged config synchronized with the wrapper's production
    # readback gate, including its exact installed filter and PID paths.
    load_wrapper().validate_tinyproxy_config(
        (ASSETS / "galileo-tinyproxy.conf").read_bytes(),
        proxy_port=18888,
        filter_path="/etc/tinyproxy/galileo.filter",
    )

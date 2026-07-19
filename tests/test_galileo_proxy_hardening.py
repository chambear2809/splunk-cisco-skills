from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.regression_helpers import REPO_ROOT


SKILL = REPO_ROOT / "skills/galileo-lemonade-instrumentation-setup"
SCRIPTS = SKILL / "scripts"
RENDER = SCRIPTS / "render_collector_config.py"
VALIDATE = SCRIPTS / "validate_collector_config.py"
RENDER_FILTER = SCRIPTS / "render_tinyproxy_filter.py"


def load_wrapper(name: str):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / "collector_runtime_wrapper.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_document() -> dict[str, object]:
    return {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": "127.0.0.1:4318"}}}},
        "processors": {"memory_limiter": {}, "batch": {}},
        "exporters": {
            "otlphttp/splunk": {"endpoint": "https://ingest.example.invalid/v2/trace"}
        },
        "service": {
            "pipelines": {
                "traces": {
                    "receivers": ["otlp"],
                    "processors": ["memory_limiter", "batch"],
                    "exporters": ["otlphttp/splunk"],
                }
            }
        },
    }


def test_renderer_scopes_literal_proxy_to_galileo_and_validator_keeps_splunk_direct(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "rendered.yaml"
    base.write_text(yaml.safe_dump(base_document(), sort_keys=False), encoding="utf-8")
    rendered = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--mode",
            "client-fanout",
            "--galileo-proxy-url",
            "http://127.0.0.1:19090",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert document["exporters"]["otlp_http/galileo_lemonade"]["proxy_url"] == (
        "http://127.0.0.1:19090"
    )
    assert (
        document["exporters"]["otlphttp/splunk"]
        == base_document()["exporters"]["otlphttp/splunk"]
    )
    accepted = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(output),
            "--mode",
            "client-fanout",
            "--galileo-proxy-url",
            "http://127.0.0.1:19090",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr

    document["exporters"]["otlphttp/splunk"]["proxy_url"] = "http://127.0.0.1:19090"
    output.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(VALIDATE),
            "--collector-config",
            str(output),
            "--mode",
            "client-fanout",
            "--galileo-proxy-url",
            "http://127.0.0.1:19090",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "must remain direct" in rejected.stderr


def test_renderer_migrates_only_the_exact_pre_proxy_managed_shape(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.yaml"
    legacy = tmp_path / "legacy.yaml"
    migrated = tmp_path / "migrated.yaml"
    base.write_text(yaml.safe_dump(base_document(), sort_keys=False), encoding="utf-8")
    first = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--base",
            str(base),
            "--output",
            str(legacy),
            "--mode",
            "client-fanout",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    document = yaml.safe_load(legacy.read_text(encoding="utf-8"))
    document["exporters"]["otlp_http/galileo_lemonade"].pop("proxy_url")
    legacy.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--base",
            str(legacy),
            "--output",
            str(migrated),
            "--mode",
            "client-fanout",
            "--galileo-proxy-url",
            "http://127.0.0.1:19090",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    migrated_document = yaml.safe_load(migrated.read_text(encoding="utf-8"))
    assert (
        migrated_document["exporters"]["otlp_http/galileo_lemonade"]["proxy_url"]
        == "http://127.0.0.1:19090"
    )


@pytest.mark.parametrize(
    "proxy_url",
    (
        "https://127.0.0.1:18888",
        "http://localhost:18888",
        "http://0.0.0.0:18888",
        "http://127.0.0.1",
        "http://user@127.0.0.1:18888",
        "http://127.0.0.1:18888/path",
    ),
)
def test_renderer_rejects_noncanonical_proxy_urls(
    tmp_path: Path, proxy_url: str
) -> None:
    base = tmp_path / "base.yaml"
    output = tmp_path / "rendered.yaml"
    base.write_text(yaml.safe_dump(base_document()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--base",
            str(base),
            "--output",
            str(output),
            "--mode",
            "client-fanout",
            "--galileo-proxy-url",
            proxy_url,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not output.exists()


def exact_config(filter_path: Path, port: int = 18888) -> bytes:
    return (
        "User tinyproxy\n"
        "Group tinyproxy\n"
        "Listen 127.0.0.1\n"
        f"Port {port}\n"
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


def test_filter_and_config_are_exact_host_deny_by_default(tmp_path: Path) -> None:
    module = load_wrapper("galileo_proxy_exact_policy_test")
    host = "api.tenant-2.example"
    rule = rb"^api\.tenant-2\.example$" + b"\n"
    module.validate_tinyproxy_filter(rule, host)
    module.validate_tinyproxy_config(
        exact_config(tmp_path / "galileo.filter"),
        proxy_port=18888,
        filter_path=str(tmp_path / "galileo.filter"),
    )
    for broad in (
        rb".*\.example$" + b"\n",
        rule + rb"^other\.example$" + b"\n",
        rb"^API\.TENANT-2\.EXAMPLE$" + b"\n",
    ):
        with pytest.raises(ValueError, match="exact escaped Galileo host"):
            module.validate_tinyproxy_filter(broad, host)
    with pytest.raises(ValueError, match="must not contain upstream"):
        module.validate_tinyproxy_config(
            exact_config(tmp_path / "galileo.filter")
            + b"Upstream http upstream.example:8080\n",
            proxy_port=18888,
            filter_path=str(tmp_path / "galileo.filter"),
        )


@pytest.mark.parametrize(
    ("extra_directive", "error"),
    (
        (b"Bind 192.0.2.10\n", "unsupported directive: bind"),
        (b'LogFile "/tmp/tinyproxy.log"\n', "unsupported directive: logfile"),
        (b"StatHost stats.example.invalid\n", "unsupported directive: stathost"),
        (b"ViaProxyName alternate-name\n", "unsupported directive: viaproxyname"),
        (b"Allow 127.0.0.1\n", "must contain exactly `Allow 127.0.0.1`"),
        (b"ConnectPort 80\n", "must contain exactly `ConnectPort 443`"),
    ),
)
def test_config_validator_rejects_every_extra_or_duplicate_directive(
    tmp_path: Path, extra_directive: bytes, error: str
) -> None:
    module = load_wrapper("galileo_proxy_exact_directive_test")
    filter_path = tmp_path / "galileo.filter"
    with pytest.raises(ValueError, match=error):
        module.validate_tinyproxy_config(
            exact_config(filter_path) + extra_directive,
            proxy_port=18888,
            filter_path=str(filter_path),
        )


def test_filter_renderer_derives_host_from_validated_endpoint(tmp_path: Path) -> None:
    output = tmp_path / "galileo.filter"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER_FILTER),
            "--galileo-traces-endpoint",
            "https://api.customer.galileo.example/otel/v1/traces",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="ascii") == (
        r"^api\.customer\.galileo\.example$" + "\n"
    )
    rejected = subprocess.run(
        [
            sys.executable,
            str(RENDER_FILTER),
            "--galileo-traces-endpoint",
            "https://api.customer.galileo.example:444/otel/v1/traces",
            "--output",
            str(tmp_path / "bad.filter"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode != 0


class FakePeer:
    def __init__(self, response: bytes, requests: list[bytes]) -> None:
        self.response = response
        self.requests = requests
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent += data
        self.requests.append(data)

    def recv(self, _size: int) -> bytes:
        response, self.response = self.response, b""
        return response


def test_live_probes_are_bounded_exact_and_credential_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_wrapper("galileo_proxy_live_probe_test")
    requests: list[bytes] = []
    responses = [
        b"HTTP/1.1 403 Filtered\r\nContent-Length: 0\r\n\r\n",
        b"HTTP/1.1 200 Connection established\r\n\r\n",
    ]

    def connect(address: tuple[str, int], timeout: float):
        assert address == ("127.0.0.1", 18888)
        assert timeout == module.PROXY_PROBE_TIMEOUT_SECONDS
        return FakePeer(responses.pop(0), requests)

    monkeypatch.setattr(module.socket, "create_connection", connect)
    module.probe_tinyproxy("http://127.0.0.1:18888", "api.tenant.example")
    assert len(requests) == 2
    assert b"CONNECT denied.invalid:443" in requests[0]
    assert b"CONNECT api.tenant.example:443" in requests[1]
    transcript = b"".join(requests).lower()
    for forbidden in (b"galileo-api-key", b"authorization", b"test-only-value"):
        assert forbidden not in transcript


@pytest.mark.parametrize("changed_asset", ("binary", "config", "filter"))
def test_proxy_identity_drift_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_asset: str,
) -> None:
    module = load_wrapper(f"galileo_proxy_identity_{changed_asset}_test")
    monkeypatch.setattr(module.sys, "platform", "darwin")
    binary = tmp_path / "tinyproxy"
    config = tmp_path / "galileo.conf"
    filter_path = tmp_path / "galileo.filter"
    binary.write_bytes(b"reviewed tinyproxy binary")
    binary.chmod(0o700)
    filter_path.write_text(r"^api\.tenant\.example$" + "\n", encoding="ascii")
    filter_path.chmod(0o600)
    config.write_bytes(exact_config(filter_path))
    config.chmod(0o600)

    descriptor, binary_provenance = module.open_trusted_executable(binary, None)
    os.close(descriptor)
    _, config_provenance = module.read_trusted_proxy_asset(config, "config", None)
    _, filter_provenance = module.read_trusted_proxy_asset(filter_path, "filter", None)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "control": module.TINYPROXY_CONTROL,
                "proxy_url": "http://127.0.0.1:18888",
                "allowed_connect_host": "api.tenant.example",
                "allowed_connect_port": 443,
                "binary": binary_provenance,
                "config": config_provenance,
                "filter": filter_provenance,
            }
        ),
        encoding="utf-8",
    )
    evidence.chmod(0o400)
    environment = {
        "GALILEO_PROXY_URL": "http://127.0.0.1:18888",
        "GALILEO_TINYPROXY_EVIDENCE_FILE": str(evidence),
    }
    probes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module,
        "probe_tinyproxy",
        lambda url, host: probes.append((url, host)),
    )
    module.validate_tinyproxy_contract(
        environment, "https://api.tenant.example/otel/v1/traces"
    )
    assert probes == [("http://127.0.0.1:18888", "api.tenant.example")]

    target = {"binary": binary, "config": config, "filter": filter_path}[changed_asset]
    target.chmod(0o600 if changed_asset != "binary" else 0o700)
    with target.open("ab") as handle:
        handle.write(b"drift")
    with pytest.raises(ValueError, match="drifted|evidence does not match"):
        module.validate_tinyproxy_contract(
            environment, "https://api.tenant.example/otel/v1/traces"
        )


def test_collector_child_never_inherits_ambient_proxy_contract() -> None:
    module = load_wrapper("galileo_proxy_environment_strip_test")
    source = {
        "HTTP_PROXY": "http://ambient.invalid:8080",
        "HTTPS_PROXY": "http://ambient.invalid:8080",
        "ALL_PROXY": "socks5://ambient.invalid:1080",
        "NO_PROXY": "api.tenant.example",
        "http_proxy": "http://ambient.invalid:8080",
        "KEEP": "value",
    }
    assert module.restricted_transport_environment(source) == {"KEEP": "value"}


def test_nonroot_service_group_can_read_but_not_write_proxy_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_wrapper("galileo_proxy_evidence_group_test")
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(module.os, "getegid", lambda: 2001)
    monkeypatch.setattr(module.os, "getgroups", lambda: [2001, 2002])

    def metadata(mode: int, gid: int) -> os.stat_result:
        return os.stat_result((stat.S_IFREG | mode, 1, 1, 1, 0, gid, 100, 0, 0, 0))

    module.validate_evidence_access_metadata(metadata(0o440, 2001))
    for rejected in (metadata(0o400, 2001), metadata(0o440, 2999)):
        with pytest.raises(ValueError, match="collector service"):
            module.validate_evidence_access_metadata(rejected)
